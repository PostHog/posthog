import { transform } from '@babel/standalone'

import { presets } from './presets'

process.stdin.setEncoding('utf8')

let type: 'site' | 'frontend' = 'site'

for (let i = 2; i < process.argv.length; i++) {
    const arg = process.argv[i]
    if (arg === '--type' && process.argv[i + 1]) {
        type = process.argv[++i] as any
        if (type !== 'site' && type !== 'frontend') {
            console.error(`Unknown app type: ${type}`)
            process.exit(1)
        }
    } else {
        console.error(`Unknown argument: ${arg}`)
        process.exit(1)
    }
}
const { wrapper, ...options } = presets[type]

let code = ''
process.stdin.on('readable', () => {
    let chunk: string
    while ((chunk = process.stdin.read())) {
        code += chunk
    }
})

process.stdin.on('end', () => {
    try {
        let output = transform(code, options).code
        if (output) {
            if (wrapper) {
                output = wrapper(output)
            }
            process.stdout.write(output, 'utf8')
        } else {
            throw new Error('Could not transpile code')
        }
    } catch (error: any) {
        console.error(error.message)
        process.exit(1)
    }
})
