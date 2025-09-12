import { SalesforceMeta, SalesforcePluginConfig, verifyConfig } from '../index'

describe('config validation', () => {
    let config: SalesforcePluginConfig

    beforeEach(() => {
        config = {
            salesforceHost: 'https://example.io',
            eventPath: 'test',
            eventMethodType: 'test',
            username: 'test',
            password: 'test',
            consumerKey: 'test',
            consumerSecret: 'test',
            eventsToInclude: '$pageview',
            propertiesToInclude: '',
            eventEndpointMapping: '',
            debugLogging: '',
        }
    })

    it('rejects an invalid URL', () => {
        config.salesforceHost = 'not a url'
        expect(() => verifyConfig({ config } as SalesforceMeta)).toThrow('host not a valid URL!')
    })

    it('accepts a valid URL', () => {
        config.salesforceHost = 'http://bbc.co.uk'
        expect(() => verifyConfig({ config } as SalesforceMeta)).not.toThrow('host not a valid URL!')
    })

    it('rejects an FTP URL', () => {
        config.salesforceHost = 'ftp://bbc.co.uk'
        expect(() => verifyConfig({ config } as SalesforceMeta)).toThrow('host not a valid URL!')
    })

    it('allows empty eventPath when v2 mapping is present', () => {
        config.eventsToInclude = ''
        config.eventEndpointMapping = JSON.stringify({ pageview: { salesforcePath: '/test', method: 'POST' } })
        expect(() => verifyConfig({ config } as SalesforceMeta)).not.toThrow()
    })

    it('requires eventPath when v2 mapping is not present', () => {
        config.eventsToInclude = '$pageview'
        config.eventPath = ''
        config.eventEndpointMapping = ''
        expect(() => verifyConfig({ config } as SalesforceMeta)).toThrow(
            'If you are not providing an eventEndpointMapping then you must provide the salesforce path.'
        )
    })
})
