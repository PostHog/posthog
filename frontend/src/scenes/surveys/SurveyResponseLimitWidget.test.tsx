import { render, screen } from '@testing-library/react'
import { initKeaTests } from '~/test/init'
import { SurveyResponseLimitWidget } from './SurveyResponseLimitWidget'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

describe('SurveyResponseLimitWidget', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('should not render for admin users', () => {
        userLogic.mount()
        billingLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: true,
        } as any)

        billingLogic.actions.loadBillingSuccess({
            usage_summary: {
                survey_responses: {
                    usage: 100,
                    limit: 250,
                },
            },
        } as any)

        render(<SurveyResponseLimitWidget />)

        expect(screen.queryByText(/Survey Responses This Month/)).not.toBeInTheDocument()
    })

    it('should not render when no billing data is available', () => {
        userLogic.mount()
        billingLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
        } as any)

        billingLogic.actions.loadBillingSuccess({
            usage_summary: {},
        } as any)

        render(<SurveyResponseLimitWidget />)

        expect(screen.queryByText(/Survey Responses This Month/)).not.toBeInTheDocument()
    })

    it('should render usage information for non-admin users', () => {
        userLogic.mount()
        billingLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
        } as any)

        billingLogic.actions.loadBillingSuccess({
            usage_summary: {
                survey_responses: {
                    usage: 100,
                    limit: 250,
                },
            },
        } as any)

        render(<SurveyResponseLimitWidget />)

        expect(screen.getByText(/Survey Responses This Month: 100 \/ 250/)).toBeInTheDocument()
        expect(screen.getByText('150 remaining')).toBeInTheDocument()
    })

    it('should show warning when approaching limit', () => {
        userLogic.mount()
        billingLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
        } as any)

        billingLogic.actions.loadBillingSuccess({
            usage_summary: {
                survey_responses: {
                    usage: 200,
                    limit: 250,
                },
            },
        } as any)

        render(<SurveyResponseLimitWidget />)

        expect(screen.getByText(/You're approaching your monthly limit/)).toBeInTheDocument()
        expect(screen.getByText('50 remaining')).toBeInTheDocument()
    })

    it('should show error when limit is reached', () => {
        userLogic.mount()
        billingLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
        } as any)

        billingLogic.actions.loadBillingSuccess({
            usage_summary: {
                survey_responses: {
                    usage: 250,
                    limit: 250,
                },
            },
        } as any)

        render(<SurveyResponseLimitWidget />)

        expect(screen.getByText(/You've reached your monthly limit/)).toBeInTheDocument()
        expect(screen.getByText('Limit reached')).toBeInTheDocument()
    })
})
