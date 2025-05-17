import * as fs from 'fs';

function main() {
    // load dist/toolbar.js and check that some strings are not in it
    const file = fs.readFileSync('dist/toolbar.js', 'utf8').toString()

    if (file.includes('new Function(')) {
        console.error('Toolbar should not include new Function()')
        process.exit(1)
    }

    // Use a regex, we do actually have the string "eval(" in the code, but it's as a string literal
    if (/(^")eval\(/g.test(file)) {
        console.error('Toolbar should not include eval()')
        process.exit(1)
    }
}


main()