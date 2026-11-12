import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { toolbarExtensionLogic } from './toolbarExtensionLogic'

type Chrome = { runtime?: { sendMessage: jest.Mock; lastError?: unknown } }

describe('toolbarExtensionLogic', () => {
    afterEach(() => {
        delete (window as { chrome?: Chrome }).chrome
    })

    test.each<[string, Chrome | undefined, boolean]>([
        ['another browser, or Chrome without the extension', undefined, false],
        [
            'Chrome with the extension',
            { runtime: { sendMessage: jest.fn((_id, _message, callback) => callback({ installed: true })) } },
            true,
        ],
        [
            'Chrome where only another extension exposes chrome.runtime',
            {
                runtime: {
                    sendMessage: jest.fn((_id, _message, callback) => callback(undefined)),
                    lastError: { message: 'Could not establish connection' },
                },
            },
            false,
        ],
    ])('detects the extension in %s', async (_, chrome, installed) => {
        ;(window as { chrome?: Chrome }).chrome = chrome
        initKeaTests()

        const logic = toolbarExtensionLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ extensionInstalled: installed })
    })
})
