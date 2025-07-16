lexer grammar HogQLLexer;

@header {                        // make <cctype> visible in the generated .cpp
  #include <cctype>
}

@members {
    /**  Is `<…` the start of an opening tag?  */
    bool isOpeningTag() {
        // Char right after '<'
        int la1 = _input->LA(1);
        if (!std::isalpha(la1) && la1 != '_' )               // need a letter or '_' to start a tag name
            return false;

        // Skip over the tag name ([a-zA-Z0-9_-]*)
        size_t i = 2;
        int ch;
        while (true) {
            ch = _input->LA(i);
            if (std::isalnum(ch) || ch == '_' || ch == '-')
                ++i;
            else
                break;
        }

        // Valid delimiter after the name?
        return ch == '>'            // `<div>`
            || ch == '/'            // `<div/>`
            || std::isspace(ch);    // `<div x=1>`
    }
}