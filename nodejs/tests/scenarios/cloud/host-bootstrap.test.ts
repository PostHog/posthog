import { spawnSync } from 'child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

const BOOTSTRAP = path.join(__dirname, 'host-bootstrap.sh')

describe('host-bootstrap.sh', () => {
    let dir: string

    beforeEach(() => {
        dir = mkdtempSync(path.join(os.tmpdir(), 'host-bootstrap-'))
    })

    afterEach(() => rmSync(dir, { recursive: true, force: true }))

    it('powers the host off when the package install fails before the AWS CLI exists', () => {
        const bin = path.join(dir, 'bin')
        mkdirSync(bin)
        writeFileSync(path.join(bin, 'apt-get'), '#!/usr/bin/env bash\nexit 100\n', { mode: 0o755 })
        writeFileSync(path.join(bin, 'poweroff'), `#!/usr/bin/env bash\ntouch "${dir}/powered-off"\n`, {
            mode: 0o755,
        })

        const result = spawnSync('bash', [BOOTSTRAP], {
            env: {
                PATH: `${bin}:/usr/bin:/bin`,
                HOME: dir,
                SCENARIO_RUN_ID: '00000000-0000-4000-8000-000000000001',
                SCENARIO_EVIDENCE_BUCKET: 'test-evidence',
                SCENARIO_BOOTSTRAP_LOG: path.join(dir, 'bootstrap.log'),
            },
            encoding: 'utf8',
        })

        expect(result.status).not.toBe(0)
        expect(existsSync(path.join(dir, 'powered-off'))).toBe(true)
    })
})
