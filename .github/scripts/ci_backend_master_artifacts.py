import re
import stat
import shutil
import zipfile
from pathlib import Path, PurePosixPath

DEFAULT_MAX_BYTES = 2 * 1024**3
DEFAULT_MAX_MEMBERS = 10000


def validate_artifact_name(name: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", name) is None:
        raise ValueError("Artifact name must be a single safe path component")
    return name


def _member_path(member: zipfile.ZipInfo) -> PurePosixPath:
    name = member.filename
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or "\\" in name
        or ":" in name
        or not name.isprintable()
        or name.rstrip("/") != path.as_posix()
    ):
        raise ValueError("Artifact contains an unsafe member path")
    kind = stat.S_IFMT(member.external_attr >> 16)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind == stat.S_IFDIR and not member.is_dir()):
        raise ValueError("Artifact contains a link or special file")
    if member.flag_bits & 1:
        raise ValueError("Encrypted artifacts are not supported")
    return path


def _validate_archive(archive: zipfile.ZipFile, *, max_bytes: int, max_members: int) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > max_members or sum(member.file_size for member in members) > max_bytes:
        raise ValueError("Artifact exceeds the extraction limit")
    paths: dict[PurePosixPath, bool] = {}
    for member in members:
        path = _member_path(member)
        if path in paths:
            raise ValueError("Artifact contains duplicate member paths")
        paths[path] = member.is_dir()
    for path in paths:
        if any(parent in paths and not paths[parent] for parent in path.parents):
            raise ValueError("Artifact uses a file as a directory")
    return members


def extract_artifact(
    archive_path: Path,
    destination: Path,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_members: int = DEFAULT_MAX_MEMBERS,
) -> None:
    validate_artifact_name(destination.name)
    if max_bytes <= 0 or max_members <= 0:
        raise ValueError("Artifact extraction limits must be positive")
    with zipfile.ZipFile(archive_path) as archive:
        # A rejected archive must not leave attacker-chosen files in the relay workspace.
        members = _validate_archive(archive, max_bytes=max_bytes, max_members=max_members)
        destination.mkdir(parents=True, exist_ok=False)
        try:
            for member in members:
                target = destination.joinpath(*PurePosixPath(member.filename).parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(member) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output, length=1024**2)
        except Exception:
            shutil.rmtree(destination)
            raise
