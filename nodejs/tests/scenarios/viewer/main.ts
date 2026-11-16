import { parseArgs } from 'util'

import { defaultStateDir } from '../environment/environment'
import { createViewerServer } from './server'

const USAGE =
    'Usage: pnpm --dir nodejs exec tsx tests/scenarios/viewer/main.ts [--port <port>] [--host <address>] [--state-dir <dir>]'

export function main(argv: string[], env: NodeJS.ProcessEnv = process.env): void {
    const { values } = parseArgs({
        args: argv,
        options: {
            port: { type: 'string', default: '8787' },
            host: { type: 'string', default: '127.0.0.1' },
            'state-dir': { type: 'string' },
            help: { type: 'boolean', default: false },
        },
    })
    if (values.help) {
        process.stdout.write(`${USAGE}\n`)
        return
    }
    const stateDir = values['state-dir'] ?? defaultStateDir(env)
    const server = createViewerServer({ stateDir })
    server.listen(Number(values.port), values.host, () => {
        process.stdout.write(`Scenario viewer on http://${values.host}:${values.port}, reading runs from ${stateDir}\n`)
    })
}

if (require.main === module) {
    main(process.argv.slice(2))
}
