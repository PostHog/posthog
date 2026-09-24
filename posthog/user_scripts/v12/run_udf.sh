# shellcheck shell=bash
# Sourced by every wrapper in this directory after the wrapper sets UDF_NAME to the base name of its binary. Each
# version directory carries its own copy of this file, because a deployed version must not depend on files outside it.

# ClickHouse starts a wrapper with copies of its open files, including client connections. A connection stays open
# while any copy of it is open, so a long-running UDF process keeps a connection open after the server closes it,
# and the next request on that connection never gets a response. Close every inherited descriptor except stdin,
# stdout and stderr before anything else. The wrappers run under bash because sh cannot close a descriptor above 9.
for fd_path in /proc/$$/fd/*; do
    fd=${fd_path##*/}
    if (( fd > 2 )); then
        exec {fd}>&-
    fi
done

: "${UDF_NAME:?the wrapper must set UDF_NAME before it sources run_udf.sh}"
DIR_NAME=$(dirname "$0")

TEMP_DIR=$(mktemp -d -p /tmp "${UDF_NAME}_XXXXXXXXXX")
trap 'rm -rf "$TEMP_DIR"; exit' 0

case $(uname -m) in
aarch64)
    EXECUTABLE_NAME="${UDF_NAME}_aarch64"
    ;;
*)
    EXECUTABLE_NAME="${UDF_NAME}_x86_64"
    ;;
esac

# A deploy replaces the binaries in user_scripts while pooled processes still run them. Each process runs a private
# copy, so the replacement never touches a file a process is executing.
cp "$DIR_NAME/$EXECUTABLE_NAME" "$TEMP_DIR/$EXECUTABLE_NAME"
chmod +x "$TEMP_DIR/$EXECUTABLE_NAME"
"$TEMP_DIR/$EXECUTABLE_NAME" "$@"
