import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { TeamMembershipLevel } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import posthog from 'posthog-js'
import { billingLogic } from 'scenes/billing/billingLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { BillingType } from '~/types'

import type { startupProgramLogicType } from './startupProgramLogicType'

const PUBLIC_EMAIL_DOMAINS = [
    'gmail.com',
    'yahoo.com',
    'hotmail.com',
    'outlook.com',
    'aol.com',
    'protonmail.com',
    'icloud.com',
    'mail.com',
    'zoho.com',
    'yandex.com',
    'gmx.com',
    'live.com',
    'mail.ru',
]

export const RAISED_OPTIONS = [
    { label: 'Bootstrapped', value: '0' },
    { label: 'Under $100k', value: '99999' },
    { label: 'From $100k to $500k', value: '499999' },
    { label: 'From $500k to $1m', value: '999999' },
    { label: 'From $1m to $5m', value: '4999999' },
    { label: '$5m or more', value: '5000000' },
]

export const YC_BATCH_OPTIONS = [
    { label: 'Select your batch', value: '' },
    // { label: 'Summer 2025', value: 'S25' }, # Too early to show, X25 only starting in April 2025
    { label: 'Winter 2025', value: 'W25' },
    { label: 'Fall 2024', value: 'F24' },
    { label: 'Summer 2024', value: 'S24' },
    { label: 'Winter 2024', value: 'W24' },
    { label: 'Summer 2023', value: 'S23' },
    { label: 'Winter 2023', value: 'W23' },
    { label: 'Summer 2022', value: 'S22' },
    { label: 'Winter 2022', value: 'W22' },
    { label: 'Summer 2021', value: 'S21' },
    { label: 'Winter 2021', value: 'W21' },
    { label: 'Earlier batches', value: 'Earlier' },
]

export enum StartupProgramType {
    YC = 'YC',
    Startup = 'startup',
}

export interface StartupProgramFormValues {
    type: StartupProgramType
    startup_domain: string
    organization_name: string
    organization_id: string
    raised?: string
    incorporation_date?: Dayjs
    yc_batch?: string
    yc_proof_screenshot_url?: string
    yc_merch_count?: number
}

export interface StartupProgramLogicProps {
    isYC: boolean
}

function validateIncorporationDate(date: Dayjs | undefined, isYC: boolean): string | undefined {
    if (isYC) {
        return undefined
    }
    if (!date) {
        return 'Please enter your incorporation date'
    }
    if (!dayjs.isDayjs(date)) {
        return 'Invalid date format'
    }
    if (date.isAfter(dayjs())) {
        return 'Incorporation date cannot be in the future'
    }
    if (date.isBefore(dayjs().subtract(2, 'year'))) {
        return 'Company must be less than 2 years old to be eligible'
    }
    return undefined
}

function validateFunding(raised: string | undefined, isYC: boolean): string | undefined {
    if (isYC) {
        return undefined
    }
    if (!raised) {
        return 'Please select how much funding you have raised'
    }
    const raisedAmount = parseInt(raised)
    if (raisedAmount >= 5000000) {
        return 'Companies that have raised $5M or more are not eligible for the startup program'
    }
    return undefined
}

export const startupProgramLogic = kea<startupProgramLogicType>([
    path(['scenes', 'startups', 'startupProgramLogic']),
    props({} as StartupProgramLogicProps),
    key(({ isYC }: StartupProgramLogicProps) => isYC || false),
    connect({
        values: [userLogic, ['user'], organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
        actions: [paymentEntryLogic, ['showPaymentEntryModal']],
    }),
    actions({
        setFormSubmitted: (submitted: boolean) => ({ submitted }),
    }),
    reducers({
        formSubmitted: [
            false,
            {
                setFormSubmitted: (_, { submitted }) => submitted,
            },
        ],
    }),
    selectors({
        isAlreadyOnStartupPlan: [
            (s) => [s.billing],
            (billing: BillingType | null) => {
                return !!billing?.startup_program_label
            },
        ],
        isUserOrganizationOwnerOrAdmin: [
            (s) => [s.user],
            (user) => {
                return (user?.organization?.membership_level ?? 0) >= TeamMembershipLevel.Admin
            },
        ],
        domainFromEmail: [
            (s) => [s.user],
            (user) => {
                if (!user?.email) {
                    return ''
                }

                const domain = user.email.split('@')[1]
                if (PUBLIC_EMAIL_DOMAINS.includes(domain)) {
                    return ''
                }

                return domain
            },
        ],
    }),
    forms(({ values, actions, props }) => ({
        startupProgram: {
            defaults: {
                type: props.isYC ? StartupProgramType.YC : StartupProgramType.Startup,
                startup_domain: values.domainFromEmail || '',
                organization_name: values.currentOrganization?.name || '',
                organization_id: values.currentOrganization?.id || '',
                raised: undefined,
                incorporation_date: undefined,
                yc_batch: props.isYC ? '' : undefined,
                yc_proof_screenshot_url: undefined,
                yc_merch_count: props.isYC ? 1 : undefined,
            } as StartupProgramFormValues,
            errors: ({ organization_id, raised, incorporation_date, yc_batch, yc_proof_screenshot_url }) => {
                if (!values.billing?.has_active_subscription) {
                    return {
                        _form: 'You need to upgrade to a paid plan before submitting your application',
                    }
                }

                return {
                    organization_id: !organization_id ? 'Please select an organization' : undefined,
                    raised: validateFunding(raised, props.isYC),
                    incorporation_date: validateIncorporationDate(incorporation_date, props.isYC),
                    yc_batch: props.isYC && !yc_batch ? 'Please select your YC batch' : undefined,
                    yc_proof_screenshot_url:
                        props.isYC && !yc_proof_screenshot_url ? 'Please upload a screenshot' : undefined,
                }
            },
            submit: async (formValues: StartupProgramFormValues) => {
                const valuesToSubmit: Record<string, any> = {
                    program: props.isYC ? StartupProgramType.YC : StartupProgramType.Startup,
                    organization_id: formValues.organization_id,
                    yc_merch_count: formValues.yc_merch_count,
                }

                if (props.isYC) {
                    valuesToSubmit.yc_batch = formValues.yc_batch
                    valuesToSubmit.yc_proof_screenshot_url = formValues.yc_proof_screenshot_url
                }

                if (!props.isYC) {
                    valuesToSubmit.raised = formValues.raised
                    valuesToSubmit.incorporation_date = dayjs.isDayjs(formValues.incorporation_date)
                        ? formValues.incorporation_date.format('YYYY-MM-DD')
                        : undefined
                }

                try {
                    await api.create('api/billing/startups/apply', valuesToSubmit)
                    actions.setFormSubmitted(true)
                    posthog.capture('startup program application submitted', valuesToSubmit)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to submit application')
                    throw error
                }
            },
        },
    })),
])
