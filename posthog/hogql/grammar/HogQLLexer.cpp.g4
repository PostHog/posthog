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
            if (ch == 0 || ch == '\n' || ch == '\r')
                break;
            ++i;
        }
    }
}

/* ───── opening tag test ───── */

bool isOpeningTag() {
    /* first char after '<' */
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

    /*  Immediate delimiter → definitely a tag  */
    if (ch == '>' || ch == '/')
        return true;

    /*  If the next char is whitespace, look further  */
    if (std::isspace(ch)) {
        skipWsAndComments(++i); // step past first space
        ch = _input->LA(i);
        /* tag iff next non-ws/non-comment char is alnum/underscore */
        return std::isalnum(ch) || ch == '_' || ch == '>' || ch == '/';
    }

    /* anything else (operator chars, ')', '+', …) → not a tag */
    return false;
}

}
