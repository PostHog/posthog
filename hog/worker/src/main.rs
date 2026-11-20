// hog-worker does the file work of `hog error-tracking`: it reads, rewrites and writes build
// output, so hog keeps its flags, releases, uploads and output while the bytes come from the same
// Rust code posthog-cli runs.
//
// hog starts one worker per command and talks to it in JSON lines over stdin and stdout. The
// worker speaks first, then answers each request with one line, in order:
//
//   worker -> {"type":"hello","protocol":1,"version":"0.1.0"}
//   hog    -> {"op":"detect","files":[{"path":"dist/a.js","bundle":true,"map":false,"mapping":false}],"publicPathPrefix":null}
//   worker -> {"ok":true,"result":{"sourcemap":[0],"composed":[],"mapping":[]}}
//   hog    -> {"op":"read_pairs","paths":["/abs/dist/a.js"],"publicPathPrefix":null}
//   worker -> {"ok":true,"result":{"pairs":[{"id":0,"sourcePath":"/abs/dist/a.js", ...}]}}
//   hog    -> {"op":"inject","ids":[0],"mode":"event","releaseId":null,"newChunkIds":[]}
//   worker -> {"ok":true,"result":{"outcomes":[{"action":"injected","chunkId":"...","warnings":[],"pair":{...}}]}}
//   hog    -> {"op":"save","ids":[0]}
//   worker -> {"ok":true,"result":{}}
//
// An upload goes on with the same pairs:
//
//   hog    -> {"op":"fingerprint","ids":[0]}
//   worker -> {"ok":true,"result":{"targets":[0]}}
//   hog    -> {"op":"set_release","ids":[0],"releaseId":"..."}
//   worker -> {"ok":true,"result":{}}
//   hog    -> {"op":"prepare","ids":[0],"mode":"event","folder":"/tmp/hog-upload-1"}
//   worker -> {"ok":true,"result":{"prepared":[{"chunkId":"...","releaseId":null,"contentHash":"...","size":812,"path":"/tmp/hog-upload-1/0.symbolset"}]}}
//   hog    -> {"op":"css_candidates","files":["/abs/dist/a.css"],"publicPathPrefix":null}
//   worker -> {"ok":true,"result":{"candidates":[{"id":0,"mapRealPath":"/abs/dist/a.css.map"}]}}
//   hog    -> {"op":"clean_up","targets":[0],"css":[0],"roots":["/abs/dist"]}
//   worker -> {"ok":true,"result":{"deletedMaps":["/abs/dist/a.js.map"],"warnings":[]}}
//   hog    -> {"op":"proguard","path":"/abs/mapping.txt","out":"/tmp/hog-upload-1/mapping-0.symbolset"}
//   worker -> {"ok":true,"result":{"contentHash":"...","size":640}}
//
// A React Native build with Hermes works on maps alone. `clone` copies the chunk id and the release
// from Metro's packager map to the map Hermes composed, and an upload sends the composed maps:
//
//   hog    -> {"op":"load_maps","paths":["/abs/main.jsbundle.map","/abs/main.hbc.composed.map"]}
//   worker -> {"ok":true,"result":{"maps":[{"id":0,"chunkId":"...","debugId":null,"releaseId":null,"empty":false},{"unreadable":"ENOENT: ..."}]}}
//   hog    -> {"op":"set_map_release","ids":[0],"releaseId":"..."}
//   worker -> {"ok":true,"result":{}}
//   hog    -> {"op":"clone_metadata","from":0,"to":1}
//   worker -> {"ok":true,"result":{"map":{"id":1,"chunkId":"...","debugId":null,"releaseId":"...","empty":false}}}
//   hog    -> {"op":"write_maps","ids":[0,1]}
//   worker -> {"ok":true,"result":{}}
//   hog    -> {"op":"prepare_maps","ids":[1],"folder":"/tmp/hog-upload-1"}
//   worker -> {"ok":true,"result":{"containers":[{"contentHash":"...","size":640,"path":"/tmp/hog-upload-1/map-1.symbolset"}]}}
//
// `fingerprint` records what a pair's files hold, so `clean_up` can tell later that nothing
// touched them. `prepare` writes each pair's symbol set to a file for hog to send, and lets the
// pairs go: nothing reads them after it. `prepare_maps` does the same for Hermes maps, which have
// ids of their own. hog sends back to `clean_up` the stylesheets whose map no ignore pattern
// matches.
//
// A request that fails answers {"ok":false,"error":{"code":"...","message":"..."}} and the worker
// keeps running. The pairs a `read_pairs` returns stay in memory under their ids until hog closes
// stdin, which ends the worker. hog owns every decision: which files to look at, which pairs an
// ignore pattern drops, and the release. PROTOCOL changes whenever a request or an answer does,
// because hog and the worker ship as two files and must refuse to work with a stranger.

mod cleanup;
mod constant;
mod hermes;
mod memory;
mod node;
mod pair;
mod proguard;
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
use trace::Trace;

const PROTOCOL: u32 = 1;

const BAD_REQUEST: &str = "bad_request";
const INJECT_FAILED: &str = "inject_failed";
const WRITE_FAILED: &str = "write_failed";
const READ_FAILED: &str = "read_failed";
const PREPARE_FAILED: &str = "prepare_failed";
const CLEANUP_FAILED: &str = "cleanup_failed";

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
        // Symbol-set mode only: one id for each pair `needs_new_chunk_id` names, in order. hog
        // mints them, so its clock decides the timestamp inside each id.
        new_chunk_ids: Vec<String>,
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
    LoadMaps {
        paths: Vec<String>,
    },
    CloneMetadata {
        from: usize,
        to: usize,
    },
    #[serde(rename_all = "camelCase")]
    SetMapRelease {
        ids: Vec<usize>,
        release_id: Option<String>,
    },
    WriteMaps {
        ids: Vec<usize>,
    },
    PrepareMaps {
        ids: Vec<usize>,
        folder: Option<String>,
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
    Maps {
        maps: Vec<MapAnswer>,
    },
    Map {
        map: MapState,
    },
    Containers {
        containers: Vec<hermes::Built>,
    },
    Done {},
}

#[derive(Serialize)]
#[serde(untagged)]
enum MapAnswer {
    Loaded(MapState),
    Unreadable { unreadable: String },
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MapState {
    id: usize,
    chunk_id: Option<String>,
    debug_id: Option<String>,
    release_id: Option<String>,
    empty: bool,
}

fn map_state(id: usize, map: &hermes::MapFile) -> MapState {
    MapState {
        id,
        chunk_id: map.content.chunk_id.clone(),
        debug_id: map.content.debug_id.clone(),
        release_id: map.content.release_id.clone(),
        empty: map.content.is_empty(),
    }
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
    fn new(code: &'static str, message: impl ToString) -> Self {
        Failure {
            code,
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
    // A pair's id is its place here. A dropped pair leaves a hole, so ids never move.
    pairs: Vec<Option<SourcePair>>,
    maps: Vec<Option<hermes::MapFile>>,
    targets: Vec<cleanup::Target>,
    stylesheets: Vec<cleanup::CssCandidate>,
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
                for id in ids {
                    self.take(id)?;
                }
                Ok(Answer::Done {})
            }
            Request::Inject {
                ids,
                mode,
                release_id,
                new_chunk_ids,
            } => self.inject(&ids, mode, release_id.as_deref(), new_chunk_ids),
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
                    .map_err(|message| Failure::new(READ_FAILED, message))
            }
            Request::LoadMaps { paths } => Ok(self.load_maps(&paths)),
            Request::CloneMetadata { from, to } => self.clone_metadata(from, to),
            Request::SetMapRelease { ids, release_id } => {
                self.set_map_release(&ids, release_id.as_deref())
            }
            Request::WriteMaps { ids } => self.write_maps(&ids),
            Request::PrepareMaps { ids, folder } => self.prepare_maps(&ids, folder.as_deref()),
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
            .map_err(|message| Failure::new(READ_FAILED, message))?;
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
                    let id = self.pairs.len();
                    let answer = PairAnswer::Read(state(id, &pair));
                    self.pairs.push(Some(pair));
                    answer
                }
                Err(Unreadable::Skipped(skipped)) => PairAnswer::Skipped { skipped },
                Err(Unreadable::NoSourcemap) => PairAnswer::Missing(()),
            })
            .collect();
        Answer::Pairs { pairs }
    }

    fn take(&mut self, id: usize) -> Result<SourcePair, Failure> {
        self.pairs
            .get_mut(id)
            .and_then(Option::take)
            .ok_or_else(|| Failure::new(BAD_REQUEST, format!("the worker holds no pair {id}")))
    }

    // Takes the pairs out for the length of a request, so they can change in parallel.
    fn take_all(&mut self, ids: &[usize]) -> Result<Vec<SourcePair>, Failure> {
        let mut taken = Vec::with_capacity(ids.len());
        for (place, id) in ids.iter().enumerate() {
            match self.take(*id) {
                Ok(pair) => taken.push(pair),
                Err(failure) => {
                    self.put_back(&ids[..place], taken);
                    return Err(failure);
                }
            }
        }
        Ok(taken)
    }

    fn put_back(&mut self, ids: &[usize], pairs: Vec<SourcePair>) {
        for (id, pair) in ids.iter().zip(pairs) {
            self.pairs[*id] = Some(pair);
        }
    }

    fn inject(
        &mut self,
        ids: &[usize],
        mode: ReleaseMode,
        release_id: Option<&str>,
        new_chunk_ids: Vec<String>,
    ) -> Result<Answer, Failure> {
        let mut pairs = self.take_all(ids)?;

        let mut fresh = new_chunk_ids.into_iter();
        let assigned: Vec<Option<String>> = pairs
            .iter()
            .map(|pair| {
                (mode == ReleaseMode::SymbolSet && pair::needs_new_chunk_id(pair, release_id))
                    .then(|| fresh.next())
                    .flatten()
            })
            .collect();

        let results: Vec<anyhow::Result<(Action, String, Vec<String>)>> = pairs
            .par_iter_mut()
            .zip(assigned)
            .map(|(pair, new_chunk_id)| {
                let mut warnings = Vec::new();
                let (action, chunk_id) = match mode {
                    ReleaseMode::Event => pair::inject_event_mode(pair, release_id, &mut warnings)?,
                    ReleaseMode::SymbolSet => {
                        pair::inject_symbol_set_mode(pair, release_id, new_chunk_id)?
                    }
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
                    failure.get_or_insert(Failure::new(INJECT_FAILED, message));
                }
            }
        }
        self.put_back(ids, pairs);

        match failure {
            Some(failure) => Err(failure),
            None => Ok(Answer::Outcomes { outcomes }),
        }
    }

    // Unchanged pairs are written too, so every map ends in posthog-cli's canonical form.
    fn save(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let pairs = self.take_all(ids)?;

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
        self.put_back(ids, pairs);
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
            return Err(Failure::new(WRITE_FAILED, message));
        }

        write::commit(files, &self.trace).map_err(|message| Failure::new(WRITE_FAILED, message))?;
        Ok(Answer::Done {})
    }
}

impl Worker {
    fn fingerprint(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        let pairs = self.take_all(ids)?;

        let fingerprinted: Result<Vec<cleanup::Target>, String> =
            pairs.par_iter().map(cleanup::js_target).collect();
        self.put_back(ids, pairs);
        self.trace.mark("fingerprint");

        let first = self.targets.len();
        self.targets
            .extend(fingerprinted.map_err(|message| Failure::new(PREPARE_FAILED, message))?);
        Ok(Answer::Targets {
            targets: (first..self.targets.len()).collect(),
        })
    }

    fn set_release(&mut self, ids: &[usize], release_id: &str) -> Result<Answer, Failure> {
        let mut pairs = self.take_all(ids)?;

        for pair in &mut pairs {
            pair.map.release_id = Some(release_id.to_string());
        }
        self.put_back(ids, pairs);
        Ok(Answer::Done {})
    }

    fn prepare(
        &mut self,
        ids: &[usize],
        mode: ReleaseMode,
        folder: Option<&str>,
    ) -> Result<Answer, Failure> {
        let pairs = self.take_all(ids)?;
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
            .map_err(|message| Failure::new(PREPARE_FAILED, message))
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
                self.stylesheets.push(candidate);

                Some(CssCandidateAnswer {
                    id: self.stylesheets.len() - 1,
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
        let unknown = |kind: &str, id: usize| {
            Failure::new(BAD_REQUEST, format!("the worker holds no {kind} {id}"))
        };
        let failed = |message: String| Failure::new(CLEANUP_FAILED, message);
        let roots: Vec<PathBuf> = cleanup::canonical_roots(roots).map_err(failed)?;

        let mut warnings = Vec::new();
        let mut stylesheets = Vec::new();
        for id in css {
            let candidate = self
                .stylesheets
                .get(*id)
                .ok_or_else(|| unknown("stylesheet", *id))?;
            match cleanup::css_target(candidate, &roots) {
                Ok(target) => stylesheets.extend(target),
                Err(warning) => warnings.push(warning),
            }
        }
        let mut all = Vec::with_capacity(targets.len() + stylesheets.len());
        for id in targets {
            all.push(
                self.targets
                    .get(*id)
                    .ok_or_else(|| unknown("cleanup target", *id))?,
            );
        }
        all.extend(&stylesheets);

        let cleaned = cleanup::clean_up(&all).map_err(failed)?;
        self.trace.mark("clean up");

        warnings.extend(cleaned.warnings);
        Ok(Answer::Cleaned {
            deleted_maps: cleaned.deleted_maps,
            warnings,
        })
    }
}

impl Worker {
    fn load_maps(&mut self, paths: &[String]) -> Answer {
        let loaded: Vec<Result<hermes::MapFile, String>> = paths
            .par_iter()
            .map(|path| hermes::load(Path::new(path)))
            .collect();
        self.trace.mark("load maps");

        let maps = loaded
            .into_iter()
            .map(|result| match result {
                Ok(map) => {
                    let id = self.maps.len();
                    let answer = MapAnswer::Loaded(map_state(id, &map));
                    self.maps.push(Some(map));
                    answer
                }
                Err(unreadable) => MapAnswer::Unreadable { unreadable },
            })
            .collect();
        Answer::Maps { maps }
    }

    fn map_mut(&mut self, id: usize) -> Result<&mut hermes::MapFile, Failure> {
        self.maps
            .get_mut(id)
            .and_then(Option::as_mut)
            .ok_or_else(|| unknown_map(id))
    }

    fn take_map(&mut self, id: usize) -> Result<hermes::MapFile, Failure> {
        self.maps
            .get_mut(id)
            .and_then(Option::take)
            .ok_or_else(|| unknown_map(id))
    }

    fn clone_metadata(&mut self, from: usize, to: usize) -> Result<Answer, Failure> {
        let mut composed = self.take_map(to)?;

        let cloned = self
            .map_mut(from)
            .map(|packager| hermes::clone_metadata(&packager.content, &mut composed.content));
        let map = map_state(to, &composed);
        self.maps[to] = Some(composed);

        cloned.map(|()| Answer::Map { map })
    }

    fn set_map_release(
        &mut self,
        ids: &[usize],
        release_id: Option<&str>,
    ) -> Result<Answer, Failure> {
        for id in ids {
            self.map_mut(*id)?.content.release_id = release_id.map(str::to_string);
        }
        Ok(Answer::Done {})
    }

    fn write_maps(&mut self, ids: &[usize]) -> Result<Answer, Failure> {
        for id in ids {
            self.map_mut(*id)?
                .write()
                .map_err(|message| Failure::new(WRITE_FAILED, message))?;
        }
        self.trace.mark("write maps");

        Ok(Answer::Done {})
    }

    fn prepare_maps(&mut self, ids: &[usize], folder: Option<&str>) -> Result<Answer, Failure> {
        let maps: Vec<hermes::MapFile> = ids
            .iter()
            .map(|id| self.take_map(*id))
            .collect::<Result<_, _>>()?;
        let folder = folder.map(Path::new);

        let built: Result<Vec<hermes::Built>, String> = ids
            .par_iter()
            .zip(maps)
            .map(|(id, map)| {
                let path = map.path.clone();
                hermes::build(*id, map, folder)
                    .map_err(|error| format!("{}: {error:#}", path.display()))
            })
            .collect();
        self.trace.mark("prepare maps");

        built
            .map(|containers| Answer::Containers { containers })
            .map_err(|message| Failure::new(PREPARE_FAILED, message))
    }
}

fn unknown_map(id: usize) -> Failure {
    Failure::new(BAD_REQUEST, format!("the worker holds no map {id}"))
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
        pairs: Vec::new(),
        maps: Vec::new(),
        targets: Vec::new(),
        stylesheets: Vec::new(),
        trace: Trace::from_environment(),
    };
    for line in io::stdin().lock().lines() {
        let response = serde_json::from_str::<Request>(&line?)
            .map_err(|error| Failure::new(BAD_REQUEST, error))
            .and_then(|request| worker.handle(request));

        send(&match response {
            Ok(result) => Response::Ok { ok: true, result },
            Err(error) => Response::Failed { ok: false, error },
        })?;
    }
    Ok(())
}
