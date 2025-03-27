import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { TeamMembershipLevel } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
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
    { label: 'Under $100k', value: '100000' },
    { label: 'From $100k to $500k', value: '500000' },
    { label: 'From $500k to $1m', value: '1000000' },
    { label: 'From $1m to $5m', value: '5000000' },
    { label: 'More than $5m', value: '100000000000' },
]

export const YC_BATCH_OPTIONS = [
    { label: 'Select your batch', value: '' },
    { label: 'Summer 2025', value: 'S25' },
    { label: 'Spring 2025', value: 'X25' },
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

export interface StartupProgramFormValues {
    type: string
    source: string
    email: string
    first_name: string
    last_name: string
    startup_domain: string
    posthog_organization_name: string
    posthog_organization_id: string
    raised: string
    incorporation_date: Dayjs | null
    yc_batch?: string
    yc_proof_screenshot_url?: string
    customer_id?: string
}

export interface StartupProgramLogicProps {
    isYC: boolean
}

function validateIncorporationDate(date: Dayjs | null, isYC: boolean): string | undefined {
    if (!date) {
        return 'Please enter your incorporation date'
    }
    if (!dayjs.isDayjs(date)) {
        return 'Invalid date format'
    }
    if (date.isAfter(dayjs())) {
        return 'Incorporation date cannot be in the future'
    }
    if (!isYC && date.isBefore(dayjs().subtract(2, 'year'))) {
        return 'Company must be less than 2 years old to be eligible'
    }
    return undefined
}

function validateFunding(raised: string | undefined, isYC: boolean): string | undefined {
    if (!raised) {
        return 'Please select how much funding you have raised'
    }
    if (!isYC) {
        const raisedAmount = parseInt(raised)
        if (raisedAmount >= 5000000) {
            return 'Companies that have raised $5M or more are not eligible for the startup program'
        }
    }
    return undefined
}

function extractDomain(url: string): string {
    try {
        const urlObj = new URL(url.startsWith('http') ? url : `https://${url}`)
        return urlObj.hostname.replace(/^www\./, '')
    } catch {
        return url.replace(/^www\./, '')
    }
}

export const startupProgramLogic = kea<startupProgramLogicType>([
    path(['scenes', 'startups', 'startupProgramLogic']),
    props({} as StartupProgramLogicProps),
    key(({ isYC }: StartupProgramLogicProps) => isYC || false),
    connect({
        values: [userLogic, ['user'], organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
    }),
    actions({
        setFormSubmitted: (submitted: boolean) => ({ submitted }),
        validateYCBatch: true,
        setYCValidationState: (state: 'none' | 'validating' | 'valid' | 'invalid') => ({ state }),
        setYCValidationError: (error: string | null) => ({ error }),
        setVerifiedCompanyName: (name: string | null) => ({ name }),
        setUploadingScreenshot: (uploading: boolean) => ({ uploading }),
    }),
    reducers({
        formSubmitted: [
            false,
            {
                setFormSubmitted: (_, { submitted }) => submitted,
            },
        ],
        ycValidationState: [
            'none' as 'none' | 'validating' | 'valid' | 'invalid',
            {
                setYCValidationState: (_, { state }) => state,
                validateYCBatch: () => 'validating',
            },
        ],
        ycValidationError: [
            null as string | null,
            {
                setYCValidationError: (_, { error }) => error,
                validateYCBatch: () => null,
            },
        ],
        verifiedCompanyName: [
            null as string | null,
            {
                validateYCBatch: () => null,
                setYCValidationState: (state, { state: newState }) => (newState === 'valid' ? state : null),
            },
        ],
        uploadingScreenshot: [
            false,
            {
                setUploadingScreenshot: (_, { uploading }) => uploading,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        validateYCBatch: async () => {
            const { yc_batch, startup_domain, posthog_organization_name } = values.startupProgram

            if (!yc_batch || yc_batch === 'Earlier') {
                actions.setYCValidationState('valid')
                actions.setYCValidationError(null)
                return
            }

            try {
                const url = `https://yc-oss.github.io/api/batches/${yc_batch.toLowerCase()}.json`
                const response = await fetch(url)

                if (!response.ok) {
                    throw new Error('Failed to validate YC batch')
                }

                const companies = await response.json()
                const normalizedDomain = extractDomain(startup_domain)
                const normalizedOrgName = posthog_organization_name.toLowerCase().trim()

                const foundCompany = companies.find((company: any) => {
                    if (!company.website && !company.name) {
                        return false
                    }
                    const companyDomain = company.website ? extractDomain(company.website) : null
                    const companyName = company.name?.toLowerCase().trim() || ''
                    const domainMatch = companyDomain === normalizedDomain
                    const nameMatch = companyName.toLowerCase() === normalizedOrgName.toLowerCase()

                    return domainMatch || nameMatch
                })

                if (foundCompany) {
                    actions.setYCValidationState('valid')
                    actions.setYCValidationError(null)
                    actions.setVerifiedCompanyName(foundCompany.name)
                } else {
                    actions.setYCValidationState('invalid')
                    actions.setYCValidationError(
                        'Could not verify YC batch membership. Please provide a screenshot of your YC profile showing "using PostHog".'
                    )
                }
            } catch (error) {
                actions.setYCValidationState('invalid')
                actions.setYCValidationError(
                    'Failed to validate YC batch membership. Please try again or provide a screenshot.'
                )
            }
        },
        [billingLogic.actionTypes.loadBillingSuccess]: () => {
            if (values.billing?.customer_id) {
                actions.setStartupProgramValue('customer_id', values.billing.customer_id)
            }
        },
    })),
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
                type: 'contact',
                source: props.isYC ? 'YC' : 'startup',
                email: values.user?.email || '',
                first_name: values.user?.first_name || '',
                last_name: values.user?.last_name || '',
                startup_domain: values.domainFromEmail || '',
                posthog_organization_name: values.currentOrganization?.name || '',
                posthog_organization_id: values.currentOrganization?.id || '',
                customer_id: values.billing?.customer_id || '',
                raised: '',
                incorporation_date: null,
                yc_batch: props.isYC ? '' : undefined,
                yc_proof_screenshot_url: undefined,
                yc_merch_count: props.isYC ? 1 : undefined,
            },
            errors: ({ posthog_organization_name, posthog_organization_id, raised, incorporation_date, yc_batch }) => {
                if (!values.billing?.has_active_subscription) {
                    return {
                        _form: 'You need to upgrade to a paid plan before submitting your application',
                    }
                }

                return {
                    posthog_organization_name: !posthog_organization_name
                        ? 'Please enter your PostHog organization name'
                        : undefined,
                    posthog_organization_id: !posthog_organization_id ? 'Please select an organization' : undefined,
                    raised: validateFunding(raised, props.isYC),
                    incorporation_date: validateIncorporationDate(incorporation_date, props.isYC),
                    yc_batch: props.isYC && !yc_batch ? 'Please select your YC batch' : undefined,
                    _form: values.ycValidationState === 'invalid' ? values.ycValidationError : undefined,
                }
            },
            submit: async (formValues: StartupProgramFormValues) => {
                // eslint-disable-next-line no-console
                console.log('📝 Form values before submission:', formValues)
                const valuesToSubmit = {
                    ...formValues,
                    incorporation_date: dayjs.isDayjs(formValues.incorporation_date)
                        ? formValues.incorporation_date.format('YYYY-MM-DD')
                        : null,
                }
                // eslint-disable-next-line no-console
                console.log('📤 Submitting form with values:', valuesToSubmit)

                actions.setFormSubmitted(true)
            },
        },
    })),
])
