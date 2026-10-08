import { reportSourceLine, scoutLabel } from './todaySignalReports'

describe('todaySignalReports', () => {
    test.each([
        ['signals-scout-checkout-github-issues', 'Checkout GitHub issues scout'],
        ['signals-scout-react-render', 'React render scout'],
        ['signals-scout-self-driving-ui', 'Self-driving UI scout'],
    ])('names the scout for skill %s', (skill, expected) => {
        expect(scoutLabel(skill)).toEqual(expected)
    })

    test.each([
        ['one source', { source_products: ['error_tracking'] }, { line: 'Error tracking', title: 'Error tracking' }],
        [
            'a scout by its skill',
            { source_products: ['signals_scout'], scout_name: 'signals-scout-react-render' },
            { line: 'React render scout', title: 'React render scout' },
        ],
        [
            'more sources than fit',
            { source_products: ['error_tracking', 'session_replay', 'conversations'] },
            { line: 'Error tracking, Session replay +1', title: 'Error tracking, Session replay, Support' },
        ],
        ['no sources', { source_products: [], scout_name: null }, { line: 'Signals', title: '' }],
    ])('names the sources of %s', (_, report, expected) => {
        expect(reportSourceLine(report)).toEqual(expected)
    })
})
