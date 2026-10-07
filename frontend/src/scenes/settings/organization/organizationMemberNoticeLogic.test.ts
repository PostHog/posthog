import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { organizationMemberNoticeLogic } from './organizationMemberNoticeLogic'

describe('organizationMemberNoticeLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        {
            label: 'a link without a button label',
            label_: '',
            url: 'https://example.com',
            errors: { label: 'Add a button label, or clear the link' },
        },
        {
            label: 'a button label without a link',
            label_: 'Open',
            url: '',
            errors: { url: 'Add a link, or clear the button label' },
        },
        {
            label: 'a link that is not http or https',
            label_: 'Open',
            url: 'javascript:alert(1)',
            errors: { url: 'The link must start with http:// or https://' },
        },
    ])('rejects $label', ({ label_, url, errors }) => {
        const logic = organizationMemberNoticeLogic()
        logic.mount()

        logic.actions.setMemberNoticeValues({ message: 'Read the policy.', label: label_, url })

        expect(logic.values.memberNoticeValidationErrors).toMatchObject(errors)
    })

    it('resets the draft to the saved notice when the organization reloads', async () => {
        const logic = organizationMemberNoticeLogic()
        logic.mount()
        logic.actions.setMemberNoticeValues({ message: 'Unsaved draft' })

        await expectLogic(logic, () => {
            organizationLogic.actions.loadCurrentOrganizationSuccess({
                ...MOCK_DEFAULT_ORGANIZATION,
                member_notice: {
                    message: 'Saved <b>notice</b>',
                    action: { label: 'Open', url: 'https://example.com' },
                },
            })
        }).toMatchValues({
            memberNotice: { message: 'Saved <b>notice</b>', label: 'Open', url: 'https://example.com' },
            hasUnsavedMemberNotice: false,
        })
    })
})
