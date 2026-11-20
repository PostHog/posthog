// hog-worker does the file work of `hog error-tracking` with the Rust code posthog-cli runs, so
// both write the same bytes. hog starts one worker per command and talks to it in JSON lines over
// stdin and stdout. The worker sends {"type":"hello","protocol":1,"version":"0.1.0"}, then answers
// each request in order with {"ok":true,"result":R} or {"ok":false,"error":{"code","message"}},
// and keeps running after a failure. R for each `op`:
//   detect             {"sourcemap":[index],"composed":[],"mapping":[],"elf":[],"macho":[]}
//   read_pairs         {"pairs":[{"id":0,"sourcePath":"...",...} | {"skipped":"reason"} | null]}
//   inject             {"outcomes":[{"action","chunkId","warnings","pair"}]}
//   drop, save         {}
//   fingerprint        {"targets":[id]}, which record what each pair's files hold for `clean_up`
//   set_release        {}
//   prepare            {"prepared":[{"chunkId","contentHash","size","path",...} | {"skipped"}]}
//   css_candidates     {"candidates":[{"id":0,"mapRealPath":"..."} | null]}
//   clean_up           {"deletedMaps":["..."],"warnings":["..."]}
//   proguard           {"contentHash":"...","size":640} | {"invalid":"reason"}
//   load_maps          {"maps":[{"id":0,"chunkId","debugId","releaseId","empty"} | {"unreadable"}]}
//   clone_metadata     {"map":{"id":1,...}}, the `to` map with the chunk id and release of `from`
//   set_map_release    {}
//   write_maps         {}
//   prepare_maps       {"containers":[{"contentHash","size","path"}]}
//   native_candidates  {"files":[{"candidates":[{"id",...} | {"problem"}]} | {"unparseable"}]}
//   dsym_slices        {"members":[{"slices":[{"id","uuid"}]} | {"unreadable"}]}
//   source_paths       {"sources":[{"paths":["..."]} | {"failed"}]}
//   pack_native        {"unreadable":[[{"path","message"}]],"containers":[{"contentHash",...}]}
//   wrap               {"contentHash":"...","size":640}, for the parity tests
// Each architecture of a fat Mach-O is a binary with an id of its own. `pack_native` reads each
// list in `sources` once and answers one `unreadable` list for it, and one container per item.
// `prepare`, `prepare_maps` and `pack_native` write symbol sets to files for hog to send and let
// their pairs, maps and binaries go. The others stay in memory until hog closes stdin, which ends
// the worker. PROTOCOL changes whenever a request or an answer does, because hog and the worker
// ship as two files.

mod cleanup;
mod constant;
mod dsym;
mod hermes;
mod memory;
mod native;
mod node;
mod pair;
mod proguard;
mod sources;
mod trace;
mod upload;
mod wrap;
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
    NativeCandidates {
        paths: Vec<String>,
    },
    DsymSlices {
        paths: Vec<String>,
    },
    SourcePaths {
        ids: Vec<usize>,
    },
    PackNative {
        sources: Vec<Vec<String>>,
        items: Vec<PackItem>,
        folder: Option<String>,
    },
    Wrap {
        path: String,
        kind: wrap::Kind,
        out: Option<String>,
    },
}

#[derive(Deserialize)]
struct PackItem {
    id: usize,
    // A place in the request's `sources`. Null packs the binary alone.
    sources: Option<usize>,
}

#[derive(Deserialize)]
struct Candidate {
    path: String,
    bundle: bool,
    map: bool,
    mapping: bool,
    // A native binary has any name, so discovery asks for the format its first bytes give.
    native: bool,
}

struct Detected {
    sourcemap: bool,
    composed: bool,
    mapping: bool,
    native: Option<native::Format>,
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
        elf: Vec<usize>,
        macho: Vec<usize>,
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
    NativeFiles {
        files: Vec<NativeFileAnswer>,
    },
    DsymMembers {
        members: Vec<DsymMemberAnswer>,
    },
    SourcePaths {
        sources: Vec<SourcePathsAnswer>,
    },
    Packed {
        unreadable: Vec<Vec<sources::Unreadable>>,
        containers: Vec<native::Built>,
    },
    Wrapped(wrap::Wrapped),
    Done {},
}

#[derive(Serialize)]
#[serde(untagged)]
enum NativeFileAnswer {
    Parsed { candidates: Vec<CandidateAnswer> },
    Unparseable { unparseable: String },
}

#[derive(Serialize)]
#[serde(untagged)]
enum CandidateAnswer {
    Problem {
        problem: native::Problem,
    },
    #[serde(rename_all = "camelCase")]
    Valid {
        id: usize,
        debug_id: String,
        format: native::Format,
        // hog keeps the larger of two files with one debug id.
        size: usize,
    },
}

#[derive(Serialize)]
#[serde(untagged)]
enum DsymMemberAnswer {
    Read { slices: Vec<SliceAnswer> },
    Unreadable { unreadable: String },
}

#[derive(Serialize)]
struct SliceAnswer {
    id: usize,
    uuid: String,
}

#[derive(Serialize)]
#[serde(untagged)]
enum SourcePathsAnswer {
    Found { paths: Vec<String> },
    Failed { failed: String },
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
    binaries: Vec<native::Binary>,
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
            Request::NativeCandidates { paths } => Ok(self.native_candidates(&paths)),
            Request::DsymSlices { paths } => Ok(self.dsym_slices(&paths)),
            Request::SourcePaths { ids } => self.source_paths(&ids),
            Request::PackNative {
                sources,
                items,
                folder,
            } => self.pack_native(&sources, &items, folder.as_deref()),
            Request::Wrap { path, kind, out } => {
                wrap::wrap(Path::new(&path), kind, out.as_deref().map(Path::new))
                    .map(Answer::Wrapped)
                    .map_err(|error| Failure::new(READ_FAILED, format!("{error:#}")))
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
                    native: file.native.then(|| native::magic_format(path)).flatten(),
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
            elf: indices(|file| file.native == Some(native::Format::Elf)),
            macho: indices(|file| file.native == Some(native::Format::Macho)),
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

impl Worker {
    fn hold(&mut self, binary: native::Binary) -> usize {
        self.binaries.push(binary);
        self.binaries.len() - 1
    }

    fn binary(&self, id: usize) -> Result<&native::Binary, Failure> {
        self.binaries
            .get(id)
            .ok_or_else(|| Failure::new(BAD_REQUEST, format!("the worker holds no binary {id}")))
    }

    fn native_candidates(&mut self, paths: &[String]) -> Answer {
        let parsed: Vec<Result<Vec<native::Candidate>, String>> = paths
            .par_iter()
            .map(|path| native::candidates(Path::new(path)))
            .collect();
        self.trace.mark("native candidates");

        let files = parsed
            .into_iter()
            .map(|result| match result {
                Ok(candidates) => NativeFileAnswer::Parsed {
                    candidates: candidates
                        .into_iter()
                        .map(|candidate| match candidate {
                            native::Candidate::Problem(problem) => {
                                CandidateAnswer::Problem { problem }
                            }
                            native::Candidate::Valid { debug_id, binary } => {
                                CandidateAnswer::Valid {
                                    debug_id,
                                    format: binary.format(),
                                    size: binary.size(),
                                    id: self.hold(binary),
                                }
                            }
                        })
                        .collect(),
                },
                Err(unparseable) => NativeFileAnswer::Unparseable { unparseable },
            })
            .collect();
        Answer::NativeFiles { files }
    }

    fn dsym_slices(&mut self, paths: &[String]) -> Answer {
        let read: Vec<Result<Vec<dsym::Slice>, String>> = paths
            .par_iter()
            .map(|path| dsym::slices(Path::new(path)))
            .collect();
        self.trace.mark("dsym slices");

        let members = read
            .into_iter()
            .map(|result| match result {
                Ok(slices) => DsymMemberAnswer::Read {
                    slices: slices
                        .into_iter()
                        .map(|slice| SliceAnswer {
                            uuid: slice.uuid,
                            id: self.hold(slice.binary),
                        })
                        .collect(),
                },
                Err(unreadable) => DsymMemberAnswer::Unreadable { unreadable },
            })
            .collect();
        Answer::DsymMembers { members }
    }

    fn source_paths(&self, ids: &[usize]) -> Result<Answer, Failure> {
        let binaries: Vec<&native::Binary> = ids
            .iter()
            .map(|id| self.binary(*id))
            .collect::<Result<_, _>>()?;

        let sources = binaries
            .par_iter()
            .map(|binary| match binary.source_paths() {
                Ok(paths) => SourcePathsAnswer::Found { paths },
                Err(error) => SourcePathsAnswer::Failed {
                    failed: format!("{error:#}"),
                },
            })
            .collect();
        self.trace.mark("source paths");

        Ok(Answer::SourcePaths { sources })
    }

    fn pack_native(
        &mut self,
        sources: &[Vec<String>],
        items: &[PackItem],
        folder: Option<&str>,
    ) -> Result<Answer, Failure> {
        let folder = folder.map(Path::new);
        let mut work = Vec::with_capacity(items.len());
        for item in items {
            if item.sources.is_some_and(|place| place >= sources.len()) {
                let message = format!("binary {} names a source list that is not there", item.id);
                return Err(Failure::new(BAD_REQUEST, message));
            }
            work.push((item, self.binary(item.id)?));
        }

        let (collected, unreadable): (Vec<_>, Vec<_>) = sources
            .par_iter()
            .map(|paths| sources::collect(paths))
            .unzip();
        self.trace.mark("collect sources");

        let containers: Result<Vec<native::Built>, String> = work
            .par_iter()
            .map(|(item, binary)| {
                let sources = item.sources.map(|place| &collected[place]);
                native::pack(item.id, binary, sources, folder).map_err(|error| format!("{error:#}"))
            })
            .collect();
        self.trace.mark("pack native");
        self.binaries.clear();

        containers
            .map(|containers| Answer::Packed {
                unreadable,
                containers,
            })
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
        binaries: Vec::new(),
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
