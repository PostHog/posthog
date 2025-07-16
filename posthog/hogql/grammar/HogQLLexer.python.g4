lexer grammar HogQLLexer;

@header {

# put any global imports you need here
import sys

}

@members {

# In the Python runtime LA(k) returns the character **code point**
# (an int) or 0 at EOF.  Convert to str with chr().
#
# NOTE: we duplicate both helpers (opening / closing) so you can
# use the same predicates you already added to the lexer rules.
#
# Example use inside a rule:
#     : '<' {self.isOpeningTag()}? -> type(LT), pushMode(HOGQLX_TAG_OPEN);
#

def _peek_char(self, k: int) -> str:
    """Return the k-th look-ahead as a *single-char string* or '\0' at EOF."""
    c = self._input.LA(k)
    return '\0' if c == 0 else chr(c)

# <div …>  or  <br/>
def isOpeningTag(self) -> bool:
    ch1 = self._peek_char(1)
    if not (ch1.isalpha() or ch1 == '_'):
        return False

    # Skip over the tag name ([a-zA-Z0-9_-]*)
    i = 2
    while True:
        ch = self._peek_char(i)
        if ch.isalnum() or ch in ('_', '-'):
            i += 1
        else:
            break

    # After the name we expect one of:  space  |  '>'  |  '/'
    return ch in ('>', '/') or ch.isspace()

}
