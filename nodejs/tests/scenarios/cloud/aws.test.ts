import { chmodSync, mkdtempSync, rmSync, writeFileSync } from 'fs'
import os from 'os'
import path from 'path'

import { AwsError, awsCli } from './aws'

const FAKE_CLI = `#!/bin/sh
if [ "$2" = "describe-db-clusters" ]; then
  echo "An error occurred (DBClusterNotFoundFault) when calling the DescribeDBClusters operation: not found" >&2
  exit 254
fi
printf '{"maxAttempts": "%s"}' "$AWS_MAX_ATTEMPTS"
`

describe('awsCli', () => {
    let bin: string
    let env: NodeJS.ProcessEnv

    beforeEach(() => {
        bin = mkdtempSync(path.join(os.tmpdir(), 'scenario-aws-'))
        writeFileSync(path.join(bin, 'aws'), FAKE_CLI)
        chmodSync(path.join(bin, 'aws'), 0o755)
        env = { PATH: `${bin}:${process.env.PATH}` }
    })

    afterEach(() => rmSync(bin, { recursive: true, force: true }))

    it.each([
        ['failover-db-cluster', '1'],
        ['describe-db-instances', ''],
    ])('gives aws rds %s a retry budget of %j', async (operation, maxAttempts) => {
        await expect(awsCli(env).call(['rds', operation])).resolves.toEqual({ maxAttempts })
    })

    it('rejects with the exit code and the service error code', async () => {
        const failure = awsCli(env).call(['rds', 'describe-db-clusters'])

        await expect(failure).rejects.toBeInstanceOf(AwsError)
        await expect(failure).rejects.toMatchObject({ exitCode: 254, code: 'DBClusterNotFoundFault' })
    })
})
