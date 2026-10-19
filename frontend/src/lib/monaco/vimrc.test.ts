import { parseVimrc } from './vimrc'

describe('parseVimrc', () => {
    it('keeps mapping and set commands with their line numbers and skips blanks and comments', () => {
        const vimrc = ['" my settings', '', 'inoremap jj <Esc>', '  :set cursorblink  ', 'nmap H ^'].join('\n')

        expect(parseVimrc(vimrc)).toEqual({
            commands: [
                { lineNumber: 3, command: 'inoremap jj <Esc>' },
                { lineNumber: 4, command: 'set cursorblink' },
                { lineNumber: 5, command: 'nmap H ^' },
            ],
            errors: [],
        })
    })

    it('allows mappings from the colon key and keys that run an ex command', () => {
        expect(parseVimrc('map : <Esc>\nnmap S :sort')).toEqual({
            commands: [
                { lineNumber: 1, command: 'map : <Esc>' },
                { lineNumber: 2, command: 'nmap S :sort' },
            ],
            errors: [],
        })
    })

    it.each([
        ['deletes every line', '%d'],
        ['deletes matching lines', 'g/select/d'],
        ['substitutes text', 's/select/SELECT/'],
        ['sorts lines', 'sort'],
        ['shares a prefix with an allowed command', 'setfoo'],
        ['adds a suffix to an allowed command', 'set123'],
        ['overrides an option command', 'map :set :sort'],
        ['overrides a mapping command', 'noremap :map :sort'],
        ['removes an ex-command mapping', 'unmap :set'],
    ])('rejects a command that %s', (_description, command) => {
        const { commands, errors } = parseVimrc(`set relativenumber\n${command}`)

        expect(commands).toEqual([{ lineNumber: 1, command: 'set relativenumber' }])
        expect(errors).toEqual([{ lineNumber: 2, message: expect.stringContaining(command) }])
    })
})
