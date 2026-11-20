import { environmentOptions } from './environmentDisplay'

describe('environmentOptions', () => {
    it('offers every environment, then each one seen, with unset apart from an environment named default', () => {
        expect(environmentOptions([null, 'default', 'prod'], null)).toEqual([
            { value: null, label: 'All environments' },
            { value: '', label: '(no environment)' },
            { value: 'default', label: 'default' },
            { value: 'prod', label: 'prod' },
        ])
    })

    it('keeps a picked environment the window no longer has', () => {
        expect(environmentOptions(['prod'], 'staging').map((option) => option.value)).toEqual([null, 'prod', 'staging'])
    })
})
