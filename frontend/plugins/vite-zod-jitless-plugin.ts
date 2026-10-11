import type { Plugin } from 'vite'

import { ZOD_CORE_FILE, withJitlessZod } from '../../common/esbuilder/zodJitless.mjs'

export function zodJitlessPlugin(): Plugin {
    return {
        name: 'zod-jitless',
        transform(code, id) {
            const [filePath] = id.split('?')
            return ZOD_CORE_FILE.test(filePath) ? withJitlessZod(code, filePath) : null
        },
    }
}
