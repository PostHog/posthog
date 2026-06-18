lexer grammar HogQLLexer;

@header {

# put any global imports you need here
import sys

}

@members {

def _peek_char(self, k: int) -> str:
    """Return the k-th look-ahead as a *single-char string* or '\0' at EOF."""
    c = self._input.LA(k)          # int code point or IntStream.EOF (-1)
    if c < 0 or c > 0x10FFFF:      # EOF or out-of-range → sentinel
        return '\0'
    return chr(c)

def _skip_ws_and_comments(self, idx: int) -> int:
    """Return the first index ≥ idx that is *not* whitespace / single-line comment."""
    while True:
        ch = self._peek_char(idx)
        if ch.isspace():                 # spaces, newlines, tabs …
            idx += 1
            continue

        # single-line comments
        if ch == '/' and self._peek_char(idx + 1) == '/':     # //
            idx += 2
        elif ch == '-' and self._peek_char(idx + 1) == '-':   # --
            idx += 2
        elif ch == '#':                                       # #
            idx += 1
        else:
            break                                             # no ws / comment
        # consume until EOL / EOF
        while self._peek_char(idx) not in ('\0', '\n', '\r'):
            idx += 1
    return idx

# ───── opening tag test ─────
def isOpeningTag(self) -> bool:
    ch1 = self._peek_char(1)
    if not (ch1.isalpha() or ch1 == '_'):
        return False                           # not a tag name start

    # skip tag name
    i = 2
    while True:
        ch = self._peek_char(i)
        if ch.isalnum() or ch in ('_', '-'):
            i += 1
        else:
            break

    ch = self._peek_char(i)

    # immediate delimiter → tag
    if ch in ('>', '/'):
        return True

    # need to look beyond whitespace
    if ch.isspace():
        i = self._skip_ws_and_comments(i + 1)
        ch = self._peek_char(i)
        return ch in ('>', '/') or ch.isalnum() or ch == '_'

    # anything else → not a tag
    return False

}
