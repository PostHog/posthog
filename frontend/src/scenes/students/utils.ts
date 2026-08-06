import { Dayjs, dayjs } from 'lib/dayjs'
import { isEmail } from 'lib/utils/url'
import { PUBLIC_EMAIL_DOMAINS } from 'scenes/startups/constants'

import { ACADEMIC_EMAIL_DOMAIN_REGEX } from './constants'

export function validateSchoolName(schoolName: string | undefined): string | undefined {
    if (!schoolName?.trim()) {
        return 'Please enter your school or university'
    }
    return undefined
}

export function validateAcademicEmail(email: string | undefined): string | undefined {
    if (!email) {
        return 'Please enter your academic email'
    }
    if (!isEmail(email, { requireTLD: true })) {
        return 'Please enter a valid email address'
    }
    const domain = email.split('@')[1].toLowerCase()
    if (PUBLIC_EMAIL_DOMAINS.includes(domain)) {
        return 'Please use your school-issued email address, not a personal one'
    }
    if (!ACADEMIC_EMAIL_DOMAIN_REGEX.test(domain)) {
        return "This doesn't look like an academic email address (.edu or .ac). Use your school-issued address"
    }
    return undefined
}

export function validateGraduationDate(date: Dayjs | undefined): string | undefined {
    if (!date) {
        return 'Please enter your expected graduation date'
    }
    if (!dayjs.isDayjs(date)) {
        return 'Invalid date format'
    }
    if (date.isBefore(dayjs())) {
        return 'Your expected graduation date must be in the future'
    }
    if (date.isAfter(dayjs().add(8, 'year'))) {
        return 'Please pick a date within the next 8 years'
    }
    return undefined
}
