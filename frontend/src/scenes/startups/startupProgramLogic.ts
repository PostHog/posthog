import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { TeamMembershipLevel } from 'lib/constants'
import { DOMAIN_REGEX } from 'lib/constants'
import { Dayjs, dayjs } from 'lib/dayjs'
import { isEmail } from 'lib/utils'
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
    raised: string
    incorporation_date: Dayjs | null
    is_building_with_llms: string
    yc_batch?: string
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

export const startupProgramLogic = kea<startupProgramLogicType>([
    path(['scenes', 'startups', 'startupProgramLogic']),
    props({} as StartupProgramLogicProps),
    key(({ isYC }: StartupProgramLogicProps) => isYC || false),
    connect({
        values: [userLogic, ['user'], organizationLogic, ['currentOrganization'], billingLogic, ['billing']],
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
                type: 'contact',
                source: props.isYC ? 'YC' : 'startup',
                email: values.user?.email || '',
                first_name: values.user?.first_name || '',
                last_name: values.user?.last_name || '',
                startup_domain: values.domainFromEmail || '',
                posthog_organization_name: values.currentOrganization?.name || '',
                raised: '',
                incorporation_date: null,
                is_building_with_llms: '',
                yc_batch: props.isYC ? '' : undefined,
            },
            errors: ({
                email,
                first_name,
                last_name,
                startup_domain,
                posthog_organization_name,
                raised,
                incorporation_date,
                is_building_with_llms,
                yc_batch,
            }) => {
                if (!values.billing?.has_active_subscription) {
                    return {
                        _form: 'You need to upgrade to a paid plan before submitting your application',
                    }
                }

                return {
                    email: !email
                        ? 'Please enter your email'
                        : !isEmail(email)
                        ? 'Please enter a valid email address'
                        : undefined,
                    first_name: !first_name ? 'Please enter your first name' : undefined,
                    last_name: !last_name ? 'Please enter your last name' : undefined,
                    startup_domain: !startup_domain
                        ? 'Please enter your company domain'
                        : !DOMAIN_REGEX.test(startup_domain)
                        ? 'Please enter a valid domain (e.g. example.com)'
                        : undefined,
                    posthog_organization_name: !posthog_organization_name
                        ? 'Please enter your PostHog organization name'
                        : undefined,
                    raised: validateFunding(raised, props.isYC),
                    incorporation_date: validateIncorporationDate(incorporation_date, props.isYC),
                    is_building_with_llms: !is_building_with_llms
                        ? 'Please select whether you are building with LLMs'
                        : undefined,
                    yc_batch: props.isYC && !yc_batch ? 'Please select your YC batch' : undefined,
                }
            },
            submit: async (formValues: StartupProgramFormValues) => {
                const valuesToSubmit = {
                    ...formValues,
                    incorporation_date: dayjs.isDayjs(formValues.incorporation_date)
                        ? formValues.incorporation_date.format('YYYY-MM-DD')
                        : null,
                }
                // eslint-disable-next-line no-console
                console.log('Form submitted with values:', valuesToSubmit)

                actions.setFormSubmitted(true)
            },
        },
    })),
])
