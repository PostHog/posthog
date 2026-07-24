lexer grammar HogQLLexer;

@header {

#include <cctype>

}

@members {

/** Skip over whitespace and end-of-line comments (`// …`, `-- …`, `# …`). */
void skipWsAndComments(std::size_t& i) {
    for (;;) {
        int ch = _input->LA(i);
        if (std::isspace(ch)) {                       // regular whitespace
            ++i;
            continue;
        }

        /*  C++ / SQL / Bash-style single-line comments  */
        if (ch == '/' && _input->LA(i + 1) == '/') {  // //
            i += 2;
        } else if (ch == '-' && _input->LA(i + 1) == '-') { // --
            i += 2;
        } else if (ch == '#') {                       // #
            ++i;
        } else {
            break;                                    // no more ws / comments
        }
        /* consume to EOL or EOF */
        while (true) {
            ch = _input->LA(i);
            if (ch <= 0 || ch == '\n' || ch == '\r')
                break;
            ++i;
        }
    }
}

/* ───── opening tag test ───── */

bool isOpeningTag() {
    /* Decide whether a '<' opens a HogQLX tag or is the '<' comparison
       operator. This is a pure lexer heuristic, so when the two are
       genuinely ambiguous we bias toward the comparison operator — a
       comparison in a saved query must never silently re-tokenise into a
       broken tag. See the parser tests for the shapes this guards. */

    /* first char after '<' must start an identifier */
    int la1 = _input->LA(1);
    if (!std::isalpha(la1) && la1 != '_')
        return false;

    /* skip the tag name ([a-zA-Z0-9_-]*) */
    std::size_t i = 2;
    while (true) {
        int ch = _input->LA(i);
        if (std::isalnum(ch) || ch == '_' || ch == '-')
            ++i;
        else
            break;
    }

    int ch = _input->LA(i);

    /*  '<name>' — opening tag closed immediately (e.g. `<div>`).  */
    if (ch == '>')
        return true;

    /*  '<name/>' — self-closing tag. Require the '>' so a bare '/'
        (division, e.g. `a<b/c`) is not mistaken for a tag.  */
    if (ch == '/')
        return _input->LA(i + 1) == '>';

    /*  Anything other than whitespace here (operator chars, ')', '+',
        digits, EOF, …) is the comparison operator, not a tag.  */
    if (!std::isspace(ch))
        return false;

    /*  Whitespace after the name: look past ws/comments to the next
        meaningful char to decide.  */
    skipWsAndComments(++i); // step past first space
    ch = _input->LA(i);

    /*  '<name />' — self-closing with space before '/>'.  */
    if (ch == '/')
        return _input->LA(i + 1) == '>';

    /*  '<name attr…' — only a tag if the following identifier is a real
        attribute, i.e. it is followed by '='. A bare identifier after the
        name (e.g. the `and` in `a<b and c`) is a comparison continuation,
        not a tag attribute.  */
    if (std::isalpha(ch) || ch == '_') {
        ++i;
        while (true) {
            int c2 = _input->LA(i);
            if (std::isalnum(c2) || c2 == '_' || c2 == '-')
                ++i;
            else
                break;
        }
        skipWsAndComments(i);
        return _input->LA(i) == '=';
    }

    /*  '<name >' (space then '>') and everything else → comparison. An
        empty tag written with a trailing space still parses in the
        default lexer mode; biasing here keeps `x <col > y` a comparison.  */
    return false;
}

}
