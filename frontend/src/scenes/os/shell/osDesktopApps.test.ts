import { urls } from 'scenes/urls'

import { osDesktopColumns } from './osDesktopApps'

describe('osDesktopColumns', () => {
    it('puts home and the picked tools on the left, in the order of the tools list', () => {
        const { left } = osDesktopColumns([
            {
                category: 'Analytics',
                items: [
                    {
                        path: 'Product analytics',
                        label: 'Product analytics',
                        href: '/insights',
                        iconType: 'product_analytics',
                    },
                ],
            },
            {
                category: 'Behavior',
                items: [
                    { path: 'Session replay', label: 'Session replay', href: '/replay', iconType: 'session_replay' },
                ],
            },
        ])

        expect(left.map(({ label, href }) => [label, href])).toEqual([
            ['Home', urls.projectHomepage()],
            ['Product analytics', '/insights'],
            ['Session replay', '/replay'],
        ])
    })
})
