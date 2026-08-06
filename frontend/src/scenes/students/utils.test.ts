import { dayjs } from 'lib/dayjs'

import { validateAcademicEmail, validateGraduationDate } from './utils'

describe('student program validators', () => {
    it.each([
        [undefined, 'Please enter your academic email'],
        ['not-an-email', 'Please enter a valid email address'],
        ['jane@gmail.com', 'Please use your school-issued email address, not a personal one'],
        [
            'jane@acme.com',
            "This doesn't look like an academic email address (.edu or .ac). Use your school-issued address",
        ],
        ['jane@stanford.edu', undefined],
        ['JANE@STANFORD.EDU', undefined],
        ['jane@unimelb.edu.au', undefined],
        ['jane@ox.ac.uk', undefined],
    ])('validateAcademicEmail(%p) returns %p', (email, expected) => {
        expect(validateAcademicEmail(email as string | undefined)).toEqual(expected)
    })

    it.each([
        [undefined, 'Please enter your expected graduation date'],
        ['2030-06-15', 'Invalid date format'], // raw strings must not pass as dates
        [dayjs().subtract(1, 'day'), 'Your expected graduation date must be in the future'],
        [dayjs().add(2, 'year'), undefined],
        [dayjs().add(9, 'year'), 'Please pick a date within the next 8 years'],
    ])('validateGraduationDate(%p) returns %p', (date, expected) => {
        expect(validateGraduationDate(date as any)).toEqual(expected)
    })
})
