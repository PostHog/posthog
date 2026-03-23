import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

import { playerHtmlCache } from '../capture/recorder'

jest.mock('../logger', () => ({
    createLogger: () => ({
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
        child: jest.fn().mockReturnThis(),
    }),
}))

describe('playerHtmlCache', () => {
    let tmpFile: string

    beforeEach(async () => {
        playerHtmlCache.reset()
        tmpFile = path.join(os.tmpdir(), `test-player-${Date.now()}.html`)
        await fs.writeFile(tmpFile, '<html><body>test player</body></html>')
    })

    afterEach(async () => {
        await fs.rm(tmpFile, { force: true })
    })

    it('loads HTML from the given path', async () => {
        const html = await playerHtmlCache.load(tmpFile)
        expect(html).toBe('<html><body>test player</body></html>')
    })

    it('get() returns cached value after load()', async () => {
        await playerHtmlCache.load(tmpFile)
        expect(playerHtmlCache.get()).toBe('<html><body>test player</body></html>')
    })

    it('load() updates cache when called again', async () => {
        await playerHtmlCache.load(tmpFile)
        await fs.writeFile(tmpFile, '<html>updated</html>')
        await playerHtmlCache.load(tmpFile)
        expect(playerHtmlCache.get()).toBe('<html>updated</html>')
    })

    it('load() rejects when file does not exist', async () => {
        await expect(playerHtmlCache.load('/nonexistent/path/player.html')).rejects.toThrow()
    })

    it('get() throws before load() is called', () => {
        expect(() => playerHtmlCache.get()).toThrow('Player HTML not loaded')
    })

    it('reset() clears the cache', async () => {
        await playerHtmlCache.load(tmpFile)
        playerHtmlCache.reset()
        expect(() => playerHtmlCache.get()).toThrow('Player HTML not loaded')
    })
})
