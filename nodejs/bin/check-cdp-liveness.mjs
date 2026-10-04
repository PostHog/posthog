#!/usr/local/bin/node
import { checkProxy } from './check-proxy.mjs'
import { checkHttp } from './liveness-http.mjs'

async function main() {
    const args = process.argv.slice(2)
    const port = process.env.HTTP_SERVER_PORT ?? '6738'
    if (
        (args.length !== 0 && (args.length !== 1 || args[0] !== '--proxy-sidecar')) ||
        !/^[0-9]+$/.test(port) ||
        Number(port) < 1 ||
        Number(port) > 65535
    ) {
        console.error('CDP liveness: invalid arguments or HTTP_SERVER_PORT')
        return 1
    }

    const [applicationHealthy, proxy] = await Promise.all([
        checkHttp({ port: Number(port), path: '/_health' }),
        args.length === 1 ? checkProxy() : Promise.resolve({ listener: true, metrics: true }),
    ])
    if (!applicationHealthy) {
        console.error('CDP liveness: application check failed')
    }
    if (!proxy.listener) {
        console.error('CDP liveness: proxy listener check failed')
    }
    if (!proxy.metrics) {
        console.error('CDP liveness: proxy metrics check failed')
    }
    return applicationHealthy && proxy.listener && proxy.metrics ? 0 : 1
}

main().then(
    (status) => {
        process.exitCode = status
    },
    () => {
        console.error('CDP liveness: check failed')
        process.exitCode = 1
    }
)
