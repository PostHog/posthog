import { render, screen } from '@testing-library/react'
import { initKeaTests } from '~/test/init'
import { SurveyResponseLimitWidget } from './SurveyResponseLimitWidget'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { UserType } from '~/types'

describe('SurveyResponseLimitWidget', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('should not render when user is impersonated', () => {
        userLogic.mount()
        billingLogic.mount()
        organizationLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
            date_joined: '2023-01-01',
            notification_settings: {
                plugin_disabled: false,
                project_weekly_digest_disabled: {},
                all_weekly_digest_disabled: false,
            },
            events_column_config: { active: 'DEFAULT' },
            anonymize_data: false,
            toolbar_mode: 'disabled',
            has_password: true,
            is_impersonated: true,
            sensitive_session_expires_at: '2023-01-01',
            organization: null,
            team: null,
            organizations: [],
            is_email_verified: true,
            is_2fa_enabled: false,
            has_social_auth: false,
        } as UserType)

        billingLogic.actions.loadBillingSuccess({
            customer_id: 'test',
            has_active_subscription: false,
            subscription_level: 'free',
            products: [],
            usage_summary: { survey_responses: { usage: 100, limit: 250 } },
        } as any)

        organizationLogic.actions.loadOrganizationSuccess({
            id: 1,
            name: 'Test Org',
            slug: 'test-org',
            membership_level: 1,
            personalization: {},
            setup: {},
            domain_whitelist: [],
            is_member_join_email_enabled: true,
            created_at: '2023-01-01',
            updated_at: '2023-01-01',
        } as any)

        render(<SurveyResponseLimitWidget />)
        expect(screen.queryByText(/survey responses/i)).not.toBeInTheDocument()
    })

    it('should render for non-admin users with usage data', () => {
        userLogic.mount()
        billingLogic.mount()
        organizationLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
            date_joined: '2023-01-01',
            notification_settings: {
                plugin_disabled: false,
                project_weekly_digest_disabled: {},
                all_weekly_digest_disabled: false,
            },
            events_column_config: { active: 'DEFAULT' },
            anonymize_data: false,
            toolbar_mode: 'disabled',
            has_password: true,
            is_impersonated: false,
            sensitive_session_expires_at: '2023-01-01',
            organization: null,
            team: null,
            organizations: [],
            is_email_verified: true,
            is_2fa_enabled: false,
            has_social_auth: false,
        } as UserType)

        billingLogic.actions.loadBillingSuccess({
            customer_id: 'test',
            has_active_subscription: false,
            subscription_level: 'free',
            products: [],
            usage_summary: { survey_responses: { usage: 100, limit: 250 } },
        } as any)

        organizationLogic.actions.loadOrganizationSuccess({
            id: 1,
            name: 'Test Org',
            slug: 'test-org',
            membership_level: 1,
            personalization: {},
            setup: {},
            domain_whitelist: [],
            is_member_join_email_enabled: true,
            created_at: '2023-01-01',
            updated_at: '2023-01-01',
        } as any)

        render(<SurveyResponseLimitWidget />)
        expect(screen.getByText(/You have used 100 of 250 responses this month/)).toBeInTheDocument()
    })

    it('should not render when no usage data', () => {
        userLogic.mount()
        billingLogic.mount()
        organizationLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
            date_joined: '2023-01-01',
            notification_settings: {
                plugin_disabled: false,
                project_weekly_digest_disabled: {},
                all_weekly_digest_disabled: false,
            },
            events_column_config: { active: 'DEFAULT' },
            anonymize_data: false,
            toolbar_mode: 'disabled',
            has_password: true,
            is_impersonated: false,
            sensitive_session_expires_at: '2023-01-01',
            organization: null,
            team: null,
            organizations: [],
            is_email_verified: true,
            is_2fa_enabled: false,
            has_social_auth: false,
        } as UserType)

        billingLogic.actions.loadBillingSuccess({
            customer_id: 'test',
            has_active_subscription: false,
            subscription_level: 'free',
            products: [],
            usage_summary: { survey_responses: { usage: 0 } },
        } as any)

        organizationLogic.actions.loadOrganizationSuccess({
            id: 1,
            name: 'Test Org',
            slug: 'test-org',
            membership_level: 1,
            personalization: {},
            setup: {},
            domain_whitelist: [],
            is_member_join_email_enabled: true,
            created_at: '2023-01-01',
            updated_at: '2023-01-01',
        } as any)

        render(<SurveyResponseLimitWidget />)
        expect(screen.queryByText(/survey responses/i)).not.toBeInTheDocument()
    })

    it('should show warning when approaching limit', () => {
        userLogic.mount()
        billingLogic.mount()
        organizationLogic.mount()

        userLogic.actions.loadUserSuccess({
            id: 1,
            uuid: 'test',
            distinct_id: 'test',
            first_name: 'Test',
            email: 'test@example.com',
            is_staff: false,
            date_joined: '2023-01-01',
            notification_settings: {
                plugin_disabled: false,
                project_weekly_digest_disabled: {},
                all_weekly_digest_disabled: false,
            },
            events_column_config: { active: 'DEFAULT' },
            anonymize_data: false,
            toolbar_mode: 'disabled',
            has_password: true,
            is_impersonated: false,
            sensitive_session_expires_at: '2023-01-01',
            organization: null,
            team: null,
            organizations: [],
            is_email_verified: true,
            is_2fa_enabled: false,
            has_social_auth: false,
        } as UserType)

        billingLogic.actions.loadBillingSuccess({
            customer_id: 'test',
            has_active_subscription: false,
            subscription_level: 'free',
            products: [],
            usage_summary: { survey_responses: { usage: 200, limit: 250 } },
        } as any)

        organizationLogic.actions.loadOrganizationSuccess({
            id: 1,
            name: 'Test Org',
            slug: 'test-org',
            membership_level: 1,
            personalization: {},
            setup: {},
            domain_whitelist: [],
            is_member_join_email_enabled: true,
            created_at: '2023-01-01',
            updated_at: '2023-01-01',
        } as any)

        render(<SurveyResponseLimitWidget />)
        expect(screen.getByText(/You have used 200 of 250 responses this month/)).toBeInTheDocument()
    })
})
