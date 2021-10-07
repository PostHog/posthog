# Defines a dev env with python 3.9 and node. Also includes docker for running
# services. Perhaps this is a bit overkill for doing so little, but I've been
# having some issues with python env not being isolated, specifically running
# pip-compile was picking up version information from somewhere else.

let
  pkgs = import <nixpkgs> {};
in
pkgs.mkShell {
  buildInputs = [
    pkgs.python39
    pkgs.python39Packages.pip
    pkgs.python39Packages.setuptools
    pkgs.python39Packages.virtualenv

    # Required to build psycopg2
    pkgs.openssl

    # Required for frontend build
    pkgs.nodejs
    pkgs.yarn
    
    # Service dependencies
    pkgs.docker];
    
  shellHook = ''
    python -m venv env
    source env/bin/activate
  '';
}
