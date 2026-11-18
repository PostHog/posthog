import { render } from '@testing-library/react'

import { OrganizationMemberNoticeMessage } from './OrganizationMemberNoticeMessage'

describe('OrganizationMemberNoticeMessage', () => {
    it.each([
        {
            label: 'keeps bold and links',
            html: 'Read <b>how</b> we use data. <a href="https://intranet.example.com/policy" target="_blank">Policy</a>',
            expected:
                'Read <b>how</b> we use data. <a href="https://intranet.example.com/policy" target="_blank">Policy</a>',
        },
        {
            label: 'removes link tags and css',
            html: '<link rel="stylesheet" href="https://example.com/x.css"><style>body{display:none}</style><span style="color:red">Hi</span>',
            expected: '<span>Hi</span>',
        },
        {
            label: 'removes scripts, handlers and javascript urls',
            html: '<a href="javascript:alert(1)" onclick="x()">Hi</a><script>alert(1)</script><img src="x" onerror="alert(1)">',
            expected: '<a>Hi</a>',
        },
    ])('$label', ({ html, expected }) => {
        const { container } = render(<OrganizationMemberNoticeMessage html={html} />)
        expect(container.firstElementChild?.innerHTML).toEqual(expected)
    })
})
