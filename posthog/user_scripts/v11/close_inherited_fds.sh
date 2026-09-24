# shellcheck shell=bash
# Sourced by every wrapper in this directory before it starts its binary. Each version directory carries its own
# copy, because a deployed version must not depend on files outside it.
#
# ClickHouse starts a wrapper with copies of its open files, including client connections. A connection stays open
# while any copy of it is open, so a long-running UDF process keeps a connection open after the server closes it,
# and the next request on that connection never gets a response. Close every inherited descriptor except stdin,
# stdout and stderr. The wrappers run under bash because sh cannot close a descriptor above 9.
for fd_path in /proc/$$/fd/*; do
    fd=${fd_path##*/}
    if (( fd > 2 )); then
        exec {fd}>&-
    fi
done
