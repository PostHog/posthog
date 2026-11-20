// hog-worker does the file work of `hog error-tracking` with the Rust code posthog-cli runs, so
// both write the same bytes. hog starts one worker per command and talks to it in JSON lines over
// stdin and stdout. The worker sends {"type":"hello","protocol":1,"version":"0.1.0"}, then answers
// each request in order with {"ok":true,"result":R} or {"ok":false,"error":{"code","message"}},
// and keeps running after a failure. R for each `op`:
//   detect             {"sourcemap":[index],"composed":[index],"mapping":[index]}
//   read_pairs         {"pairs":[{"id":0,"sourcePath":"...",...} | {"skipped":"reason"} | null]}
//   inject             {"outcomes":[{"action","chunkId","warnings","pair"}]}
//   drop, save         {}
//   fingerprint        {"targets":[id]}, which record what each pair's files hold for `clean_up`
//   set_release        {}
//   prepare            {"prepared":[{"chunkId","contentHash","size","path",...} | {"skipped"}]}
//   css_candidates     {"candidates":[{"id":0,"mapRealPath":"..."} | null]}
//   clean_up           {"deletedMaps":["..."],"warnings":["..."]}
//   proguard           {"contentHash":"...","size":640} | {"invalid":"reason"}
// `prepare` writes each pair's symbol set to a file for hog to send and lets the pairs go. Other
// pairs stay in memory under their ids until hog closes stdin, which ends the worker. PROTOCOL
// changes whenever a request or an answer does, because hog and the worker ship as two files.

mod cleanup;
mod constant;
mod memory;
mod node;
mod pair;
mod proguard;
mod store;
mod trace;
mod upload;
mod write;

use rayon::prelude::*;
use serde::{Deserialize, Serialize};
use std::{
    io::{self, BufRead, Write},
    path::{Path, PathBuf},
};

use pair::{Action, SourcePair, Unreadable};
use store::Store;
use trace::Trace;

const PROTOCOL: u32 = 1;

const MILLIS_PER_SECOND: u64 = 1000;
const NANOS_PER_MILLI: u32 = 1_000_000;

const BAD_REQUEST: &str = "bad_request";
const FAILED: &str = "failed";

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Request {
    #[serde(rename_all = "camelCase")]
    Detect {
        files: Vec<Candidate>,
        public_path_prefix: Option<String>,
    },
    #[serde(rename_all = "camelCase")]
    ReadPairs {
        paths: Vec<String>,
        public_path_prefix: Option<String>,
    },
    Drop {
        ids: Vec<usize>,
    },
    #[serde(rename_all = "camelCase")]
    Inject {
        ids: Vec<usize>,
        mode: ReleaseMode,
        release_id: Option<String>,
        // hog's clock, in milliseconds, so its tests decide the timestamps in minted chunk ids.
        now: u64,
    },
    Save {
        ids: Vec<usize>,
    },
    Fingerprint {
        ids: Vec<usize>,
    },
    #[serde(rename_all = "camelCase")]
    SetRelease {
        ids: Vec<usize>,
        release_id: String,
    },
    Prepare {
        ids: Vec<usize>,
        mode: ReleaseMode,
        folder: Option<String>,
    },
    #[serde(rename_all = "camelCase")]
    CssCandidates {
        files: Vec<String>,
        public_path_prefix: Option<String>,
    },
    CleanUp {
        targets: Vec<usize>,
        css: Vec<usize>,
        roots: Vec<String>,
    },
    Proguard {
        path: String,
        out: Option<String>,
    },
}

#[derive(Deserialize)]
struct Candidate {
    path: String,
    bundle: bool,
    map: bool,
    mapping: bool,
}

struct Detected {
    sourcemap: bool,
    composed: bool,
    mapping: bool,
}

#[derive(Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
enum ReleaseMode {
    Event,
    SymbolSet,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Answer {
    // Indices into the request's `files`.
    Detected {
        sourcemap: Vec<usize>,
        composed: Vec<usize>,
        mapping: Vec<usize>,
    },
    Pairs {
        pairs: Vec<PairAnswer>,
    },
    Outcomes {
        outcomes: Vec<Outcome>,
    },
    Targets {
        targets: Vec<usize>,
    },
    Prepared {
        prepared: Vec<upload::Prepared>,
    },
    CssCandidates {
        candidates: Vec<Option<CssCandidateAnswer>>,
    },
    #[serde(rename_all = "camelCase")]
    Cleaned {
        deleted_maps: Vec<String>,
        warnings: Vec<String>,
    },
    Proguard(proguard::Built),
    Done {},
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct CssCandidateAnswer {
    id: usize,
    map_real_path: Option<String>,
}

#[derive(Serialize)]
#[serde(untagged)]
enum PairAnswer {
    Read(PairState),
    Skipped { skipped: String },
    Missing(()),
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct PairState {
    id: usize,
    source_path: String,
    map_path: String,
    // hog matches ignore patterns against the map's canonical path.
    map_real_path: String,
    chunk_id: Option<String>,
    source_debug_id: Option<String>,
    map_chunk_id: Option<String>,
    map_release_id: Option<String>,
    map_debug_id: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct Outcome {
    action: Action,
    chunk_id: String,
    warnings: Vec<String>,
    pair: PairState,
}

#[derive(Serialize)]
struct Hello<'a> {
    r#type: &'a str,
    protocol: u32,
    version: &'a str,
}

#[derive(Serialize)]
#[serde(untagged)]
enum Response {
    Ok { ok: bool, result: Answer },
    Failed { ok: bool, error: Failure },
}

#[derive(Serialize)]
struct Failure {
    code: &'static str,
    message: String,
}

impl Failure {
    fn bad_request(message: impl ToString) -> Self {
        Failure {
            code: BAD_REQUEST,
            message: message.to_string(),
        }
    }

    fn failed(message: impl ToString) -> Self {
        Failure {
            code: FAILED,
            message: message.to_string(),
        }
    }
}

fn display(path: &Path) -> String {
    path.to_string_lossy().into_owned()
}

fn state(id: usize, pair: &SourcePair) -> PairState {
    let map_real_path =
        dunce::canonicalize(&pair.map_path).unwrap_or_else(|_| pair.map_path.clone());

    PairState {
        id,
        source_path: display(&pair.source_path),
        map_path: display(&pair.map_path),
        map_real_path: display(&map_real_path),
        chunk_id: pair.chunk_id(),
        source_debug_id: pair.source_debug_id(),
        map_chunk_id: pair.map.chunk_id.clone(),
        map_release_id: pair.map.release_id.clone(),
        map_debug_id: pair.map.debug_id.clone(),
    }
}

struct Worker {
    pairs: Store<SourcePair>,
    targets: Store<cleanup::Target>,
    stylesheets: Store<cleanup::CssCandidate>,
    trace: Trace,
}

impl Worker {
    fn handle(&mut self, request: Request) -> Result<Answer, Failure> {
        match request {
            Request::Detect {
                files,
                public_path_prefix,
            } => self.detect(&files, public_path_prefix.as_deref()),
            Request::ReadPairs {
                paths,
                public_path_prefix,
            } => Ok(self.read_pairs(&paths, public_path_prefix.as_deref())),
            Request::Drop { ids } => {
                self.pairs.take_all(&ids)?;
                Ok(Answer::Done {})
            }
            Request::Inject {
                ids,
                mode,
                release_id,
                now,
            } => self.inject(&ids, mode, release_id.as_deref(), now),
            Request::Save { ids } => self.save(&ids),
            Request::Fingerprint { ids } => self.fingerprint(&ids),
            Request::SetRelease { ids, release_id } => self.set_release(&ids, &release_id),
            Request::Prepare { ids, mode, folder } => self.prepare(&ids, mode, folder.as_deref()),
            Request::CssCandidates {
                files,
                public_path_prefix,
            } => Ok(self.css_candidates(&files, public_path_prefix.as_deref())),
            Request::CleanUp {
                targets,
                css,
                roots,
            } => self.clean_up(&targets, &css, &roots),
            Request::Proguard { path, out } => {
                proguard::build(Path::new(&path), out.as_deref().map(Path::new))
                    .map(Answer::Proguard)
                    .map_err(Failure::failed)
            }
        }
    }

    fn detect(
        &self,
        files: &[Candidate],
        public_path_prefix: Option<&str>,
    ) -> Result<Answer, Failure> {
        let found: Vec<Result<Detected, String>> = files
            .par_iter()
            .map(|file| {
                let path = Path::new(&file.path);
                Ok(Detected {
                    sourcemap: file.bundle && pair::has_sourcemap(path, public_path_prefix),
                    composed: file.map && pair::is_composed_map(path),
                    mapping: file.mapping && proguard::is_valid_mapping(&node::read(path)?),
                })
            })
            .collect();
        self.trace.mark("detect");

        let found: Vec<Detected> = found
            .into_iter()
            .collect::<Result<_, _>>()
            .map_err(Failure::failed)?;
        let indices = |pick: fn(&Detected) -> bool| {
            found
                .iter()
                .enumerate()
                .filter(|(_, file)| pick(file))
                .map(|(index, _)| index)
                .collect()
        };
        Ok(Answer::Detected {
            sourcemap: indices(|file| file.sourcemap),
            composed: indices(|file| file.composed),
            mapping: indices(|file| file.mapping),
        })
    }

    fn read_pairs(&mut self, paths: &[String], public_path_prefix: Option<&str>) -> Answer {
        let read: Vec<Result<SourcePair, Unreadable>> = paths
            .par_iter()
            .map(|path| pair::read_pair(Path::new(path), public_path_prefix))
            .collect();
        self.trace.mark("read pairs");

        let pairs = read
            .into_iter()
            .map(|result| match result {
                Ok(pair) => {
                    let answer = state(0, &pair);
                    let id = self.pairs.hold(pair);
                    PairAnswer::Read(PairState { id, ..answer })
                }
                Err(Unreadable::Skipped(skipped)) => PairAnswer::Skipped { skipped },
                Err(Unreadable::NoSourcemap) => PairAnswer::Missing(()),
            })
            .collect();
        Answer::Pairs { pairs }
    }

    fn inject(
        &mut self,
        ids: &[usize],
        mode: ReleaseMode,
        release_id: Option<&str>,
        now: u64,
    ) -> Result<Answer, Failure> {
        let mut pairs = self.pairs.take_all(ids)?;
        let now = uuid::Timestamp::from_unix(
            uuid::NoContext,
            now / MILLIS_PER_SECOND,
            (now % MILLIS_PER_SECOND) as u32 * NANOS_PER_MILLI,
        );

        let results: Vec<anyhow::Result<(Action, String, Vec<String>)>> = pairs
            .par_iter_mut()
            .map(|pair| {
                let mut warnings = Vec::new();
                let (action, chunk_id) = match mode {
                    ReleaseMode::Event => pair::inject_event_mode(pair, release_id, &mut warnings)?,
                    ReleaseMode::SymbolSet => pair::inject_symbol_set_mode(pair, release_id, &now)?,
                };
                Ok((action, chunk_id, warnings))
            })
            .collect();
        self.trace.mark("inject");

        let mut outcomes = Vec::with_capacity(results.len());
        let mut failure = None;
        for ((id, pair), result) in ids.iter().zip(&pairs).zip(results) {
            match result {
                Ok((action, chunk_id, warnings)) => outcomes.push(Outcome {
                    action,
                    chunk_id,
                    warnings,
                    pair: state(*id, pair),
                }),
                Err(error) => {
                    let message = format!("{}: {error:#}", pair.source_path.display());
                    failure.get_or_insert(Failure::failed(message));
                }
            }
        }
        self.pairs.put_back(ids, pairs);

        match failure {
            Some(failure) => Err(failure),
            None => Ok(Answer::Outcomes { outcomes }),
        }
    }

    // Unchanged pairs are written too, so every map ends in posthog-cli's canonical form.
    fn save(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let pairs = self.pairs.take_all(ids)?;

        let staged: Vec<Result<Vec<write::Staged>, String>> = pairs
            .par_iter()
            .map(|pair| {
                let map = pair.map.serialize().map_err(|error| error.to_string())?;
                let source = write::stage(&pair.source_path, pair.source.as_bytes())?;
                match write::stage(&pair.map_path, &map) {
                    Ok(map) => Ok(vec![source, map]),
                    Err(message) => {
                        write::discard(&[source]);
                        Err(message)
                    }
                }
            })
            .collect();
        self.pairs.put_back(ids, pairs);
        self.trace.mark("stage");

        let mut files = Vec::with_capacity(staged.len() * 2);
        let mut failure = None;
        for result in staged {
            match result {
                Ok(pair) => files.extend(pair),
                Err(message) => {
                    failure.get_or_insert(message);
                }
            }
        }
        if let Some(message) = failure {
            write::discard(&files);
            return Err(Failure::failed(message));
        }

        write::commit(files, &self.trace).map_err(Failure::failed)?;
        Ok(Answer::Done {})
    }
}

impl Worker {
    fn fingerprint(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let pairs = self.pairs.take_all(ids)?;

        let fingerprinted: Result<Vec<cleanup::Target>, String> =
            pairs.par_iter().map(cleanup::js_target).collect();
        self.pairs.put_back(ids, pairs);
        self.trace.mark("fingerprint");

        let targets = fingerprinted
            .map_err(Failure::failed)?
            .into_iter()
            .map(|target| self.targets.hold(target))
            .collect();
        Ok(Answer::Targets { targets })
    }

    fn set_release(&mut self, ids: &[usize], release_id: &str) -> Result<Answer, Failure> {
        let mut pairs = self.pairs.take_all(ids)?;

        for pair in &mut pairs {
            pair.map.release_id = Some(release_id.to_string());
        }
        self.pairs.put_back(ids, pairs);
        Ok(Answer::Done {})
    }

    fn prepare(
        &mut self,
        ids: &[usize],
        mode: ReleaseMode,
        folder: Option<&str>,
    ) -> Result<Answer, Failure> {
        let pairs = self.pairs.take_all(ids)?;
        let folder = folder.map(Path::new);

        let prepared: Result<Vec<upload::Prepared>, String> = ids
            .par_iter()
            .zip(pairs)
            .map(|(id, pair)| {
                let source_path = pair.source_path.clone();
                upload::prepare(*id, pair, mode, folder)
                    .map_err(|error| format!("{}: {error:#}", source_path.display()))
            })
            .collect();
        self.trace.mark("prepare");

        prepared
            .map(|prepared| Answer::Prepared { prepared })
            .map_err(Failure::failed)
    }

    fn css_candidates(&mut self, files: &[String], public_path_prefix: Option<&str>) -> Answer {
        let found: Vec<Option<cleanup::CssCandidate>> = files
            .par_iter()
            .map(|file| cleanup::css_candidate(file, public_path_prefix))
            .collect();
        self.trace.mark("css candidates");

        let candidates = found
            .into_iter()
            .map(|candidate| {
                let candidate = candidate?;
                let map_real_path = candidate.map_path().map(|path| {
                    display(&dunce::canonicalize(path).unwrap_or_else(|_| path.to_path_buf()))
                });
                Some(CssCandidateAnswer {
                    id: self.stylesheets.hold(candidate),
                    map_real_path,
                })
            })
            .collect();
        Answer::CssCandidates { candidates }
    }

    // Bundles first, then stylesheets, each in the order hog names them, which orders the warnings.
    fn clean_up(
        &mut self,
        targets: &[usize],
        css: &[usize],
        roots: &[String],
    ) -> Result<Answer, Failure> {
        let roots: Vec<PathBuf> = cleanup::canonical_roots(roots).map_err(Failure::failed)?;

        let mut warnings = Vec::new();
        let mut stylesheets = Vec::new();
        for id in css {
            let candidate = self.stylesheets.get(*id)?;
            match cleanup::css_target(candidate, &roots) {
                Ok(target) => stylesheets.extend(target),
                Err(warning) => warnings.push(warning),
            }
        }
        let mut all = Vec::with_capacity(targets.len() + stylesheets.len());
        for id in targets {
            all.push(self.targets.get(*id)?);
        }
        all.extend(&stylesheets);

        let cleaned = cleanup::clean_up(&all).map_err(Failure::failed)?;
        self.trace.mark("clean up");

        warnings.extend(cleaned.warnings);
        Ok(Answer::Cleaned {
            deleted_maps: cleaned.deleted_maps,
            warnings,
        })
    }
}

fn send(message: &impl Serialize) -> io::Result<()> {
    let mut line = serde_json::to_vec(message)?;
    line.push(b'\n');

    let mut stdout = io::stdout().lock();
    stdout.write_all(&line)?;
    stdout.flush()
}

fn main() -> io::Result<()> {
    memory::tune_allocator();

    send(&Hello {
        r#type: "hello",
        protocol: PROTOCOL,
        version: env!("CARGO_PKG_VERSION"),
    })?;

    let mut worker = Worker {
        pairs: Store::new("pair"),
        targets: Store::new("cleanup target"),
        stylesheets: Store::new("stylesheet"),
        trace: Trace::from_environment(),
    };
    for line in io::stdin().lock().lines() {
        let response = serde_json::from_str::<Request>(&line?)
            .map_err(Failure::bad_request)
            .and_then(|request| worker.handle(request));

        send(&match response {
            Ok(result) => Response::Ok { ok: true, result },
            Err(error) => Response::Failed { ok: false, error },
        })?;
    }
    Ok(())
}
