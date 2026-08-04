import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { verifyEmailLogic } from './verifyEmailLogic'

describe('verifyEmailLogic', () => {
    let logic: ReturnType<typeof verifyEmailLogic.build>

    beforeEach(() => {
        sessionStorage.clear()
        initKeaTests()
        logic = verifyEmailLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('picks up the email from the URL and stores it for later', () => {
        router.actions.push('/verify_email/abc-123?email=jane@example.com')

        expect(logic.values.uuid).toEqual('abc-123')
        expect(logic.values.email).toEqual('jane@example.com')
        expect(sessionStorage.getItem('ph_verify_email_uuid')).toEqual('abc-123')
        expect(sessionStorage.getItem('ph_verify_email_address')).toEqual('jane@example.com')
    })

    it('recovers uuid and email from session storage when the URL drops the uuid', () => {
        router.actions.push('/verify_email/abc-123?email=jane@example.com')
        router.actions.push('/verify_email')

        expect(logic.values.view).toEqual('pending')
        expect(logic.values.uuid).toEqual('abc-123')
        expect(logic.values.email).toEqual('jane@example.com')
    })

    it('falls back to the invalid view when there is nothing to recover', () => {
        router.actions.push('/verify_email')

        expect(logic.values.view).toEqual('invalid')
        expect(logic.values.uuid).toBeNull()
    })

    it('clears the stored uuid and email once verification succeeds', () => {
        router.actions.push('/verify_email/abc-123?email=jane@example.com')
        logic.actions.setView('success')

        expect(sessionStorage.getItem('ph_verify_email_uuid')).toBeNull()
        expect(sessionStorage.getItem('ph_verify_email_address')).toBeNull()
    })
})
