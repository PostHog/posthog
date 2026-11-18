import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import zxcvbn from 'zxcvbn'

import { loadPasswordEstimator, validatePassword } from 'lib/components/PasswordStrength'

import { initKeaTests } from '~/test/init'

import { SignupPasswordStrength } from './SignupPasswordStrength'

jest.mock('zxcvbn', () => ({
    __esModule: true,
    default: jest.fn(jest.requireActual('zxcvbn')),
}))

describe('SignupPasswordStrength', () => {
    it('displays the validation analysis without estimating the password again', async () => {
        initKeaTests()
        await loadPasswordEstimator()
        jest.mocked(zxcvbn).mockClear()
        const password = 'violet-satellite-otter-cobalt'
        const validatedPassword = validatePassword(password)

        render(
            <SignupPasswordStrength
                password={password}
                validatedPassword={validatedPassword}
                estimatorLoading={false}
            />
        )

        expect(await screen.findByText('25 hedgehog lifetimes')).toBeVisible()
        expect(screen.getByText('or 74 years')).toBeVisible()
        expect(zxcvbn).toHaveBeenCalledTimes(1)
    })
})
