import { defaultConfig } from '~/common/config/config'

import { createPersonHogClient } from './index'

describe('createPersonHogClient', () => {
    it('builds no client for an empty target address, even when the default address is set', () => {
        const config = { ...defaultConfig, PERSONHOG_ENABLED: true, PERSONHOG_ADDR: 'replica-router:50052' }

        expect(createPersonHogClient(config, { addr: '', clientName: 'test-leader' })).toBeNull()
    })
})
