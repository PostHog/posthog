import { parseArgs } from 'util'

import { defaultStateDir } from '../environment/environment'
import { CARDS_DIR } from './catalog'
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
    const port = Number(values.port)
    if (!Number.isInteger(port) || port < 0 || port > 65535) {
        process.stderr.write(`--port ${values.port} is not a port number\n${USAGE}\n`)
        process.exitCode = 1
        return
    }
    const stateDir = values['state-dir'] ?? defaultStateDir(env)
    const server = createViewerServer({ stateDir, cardsDir: CARDS_DIR })
    server.on('error', (error) => {
        process.stderr.write(`The viewer cannot listen on ${values.host}:${port}: ${error.message}\n`)
        process.exitCode = 1
    })
    server.listen(port, values.host, () => {
        process.stdout.write(`Scenario viewer on http://${values.host}:${values.port}, reading runs from ${stateDir}\n`)
    })
}

if (require.main === module) {
    main(process.argv.slice(2))
}
