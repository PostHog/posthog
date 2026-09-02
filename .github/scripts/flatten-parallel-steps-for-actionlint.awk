/^[ ]*- parallel:[ ]*$/ {
    parallel_indent = match($0, /[^ ]/) - 1
    dedent = 0
    in_parallel = 1
    next
}

in_parallel {
    if ($0 ~ /^[ ]*$/) {
        print
        next
    }

    indent = match($0, /[^ ]/) - 1
    if (indent <= parallel_indent) {
        in_parallel = 0
        print
        next
    }

    if (!dedent) {
        dedent = indent - parallel_indent
    }
    print substr($0, dedent + 1)
    next
}

{ print }
