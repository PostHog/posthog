import * as fs from 'fs'

import { exec } from './execute'

// get filename from first cli arg
const filename = process.argv[2]

// raise if filename does not end with ".hoge"
if (!filename.endsWith('.hoge')) {
    throw new Error("filename must end with '.hoge'")
}

// read file
const code = JSON.parse(fs.readFileSync(filename, 'utf8'))

// execute code
exec(code)
