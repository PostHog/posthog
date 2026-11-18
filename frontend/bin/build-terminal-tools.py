import io
import sys
import gzip
import json
import hashlib
import tarfile
import tempfile
from pathlib import Path

import requests

FRONTEND = Path(__file__).resolve().parents[1]
ASSETS = FRONTEND / "src" / "scenes" / "terminal" / "assets"
MANIFEST = FRONTEND / "public" / "terminal" / "tools-manifest.json"
PREFIX = "opt/posthog-tools"


def download(url: str, algorithm: str, expected: str) -> bytes:
    with requests.get(url, timeout=60) as response:
        response.raise_for_status()
        data = response.content
    if hashlib.new(algorithm, data).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch: {url}")
    return data


def normalized(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    # The source modes follow the build host: the umask decides what mkdir and write_text produce,
    # and Linux reports every symlink as 0o777 because the kernel stores no symlink permissions.
    # Fix the modes here so the same inputs give the same archive on every machine.
    info.mode = 0o755 if info.isdir() or info.issym() or info.mode & 0o111 else 0o644
    return info


def build() -> None:
    manifest = json.loads(MANIFEST.read_text())
    with tempfile.TemporaryDirectory(prefix="posthog-terminal-tools-") as temporary:
        root = Path(temporary)
        tools = root / PREFIX
        tools.mkdir(parents=True)
        for package in manifest["packages"]:
            data = download(f"{manifest['repository']}/{package['file']}", "sha256", package["sha256"])
            # APK signatures, metadata, and payload are concatenated tar streams.
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz", ignore_zeros=True) as archive:
                members = [member for member in archive if member.name.startswith(("bin/", "etc/", "lib/", "usr/"))]
                archive.extractall(tools, members=members, filter="data")

        licenses = tools / "licenses"
        licenses.mkdir()
        for source in manifest["sources"]:
            data = download(source["url"], "sha512", source["sha512"])
            with tarfile.open(fileobj=io.BytesIO(data)) as archive:
                notices = []
                for filename in source["license_files"]:
                    license_file = archive.extractfile(filename)
                    if license_file is None:
                        raise ValueError(f"Missing license: {filename}")
                    notices.append(filename.encode() + b"\n\n" + license_file.read())
                (licenses / f"{source['name']}.txt").write_bytes(b"\n\n".join(notices))
        (licenses / "tools-manifest.json").write_text(json.dumps(manifest, indent=4) + "\n")
        (tools / "etc/nanorc").write_text(f'include "/{PREFIX}/usr/share/nano/*.nanorc"\n')
        for directory in ("etc/mc", "usr/share/mc", "usr/lib/mc"):
            link = root / directory
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(f"/{PREFIX}/{directory}")

        wrappers = root / "usr/bin"
        wrappers.mkdir(parents=True, exist_ok=True)
        for command in ("bash", "nano", "tree", "ncdu", "mc", "mcview", "mcedit", "mcdiff"):
            arguments = ""
            if command == "nano":
                arguments = f"--rcfile=/{PREFIX}/etc/nanorc "
            elif command.startswith("mc"):
                arguments = "-u "
            wrapper = wrappers / command
            binary = f"bin/{command}" if command == "bash" else f"usr/bin/{command}"
            # Isolate musl and ncurses from the guest's existing uClibc programs.
            wrapper.write_text(
                "#!/bin/sh\n"
                f"export TERMINFO=/{PREFIX}/etc/terminfo LANG=C.UTF-8\n"
                'export TZ="$(cat /etc/TZ)"\n'
                f"exec /{PREFIX}/lib/ld-musl-i386.so.1 "
                f"--library-path /{PREFIX}/lib:/{PREFIX}/usr/lib "
                f'/{PREFIX}/{binary} {arguments}"$@"\n'
            )
            wrapper.chmod(0o755)

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(root.rglob("*")):
                archive.add(path, arcname=path.relative_to(root), recursive=False, filter=normalized)
        # A fixed gzip header keeps the vendored archive reproducible.
        with io.BytesIO() as compressed:
            with gzip.GzipFile(fileobj=compressed, mode="wb", filename="", mtime=0) as output:
                output.write(buffer.getvalue())
            bundle = compressed.getvalue()
        (ASSETS / "tools-linux-i386.tar.gz.bin").write_bytes(bundle)
        (ASSETS / "hashes.json").write_text(
            json.dumps({"toolsSha256": hashlib.sha256(bundle).hexdigest()}, indent=4) + "\n"
        )
        sys.stdout.write(
            f"tools-linux-i386.tar.gz.bin: {len(bundle)} bytes, SHA-256 {hashlib.sha256(bundle).hexdigest()}\n"
        )


if __name__ == "__main__":
    build()
