import jwt from 'jsonwebtoken'

export class JWT {
    private secrets: string[] = []

    constructor(commaSeparatedSaltKeys: string) {
        const saltKeys = commaSeparatedSaltKeys.split(',').filter((key) => key)
        if (!saltKeys.length) {
            throw new Error('Encryption keys are not set')
        }
        this.secrets = saltKeys
    }

    sign(payload: object, options?: jwt.SignOptions): string {
        return jwt.sign(payload, this.secrets[0], options)
    }

    verify(
        token: string,
        options?: jwt.VerifyOptions & { ignoreVerificationErrors?: boolean }
    ): string | jwt.Jwt | jwt.JwtPayload | undefined {
        let error: Error | undefined
        for (const secret of this.secrets) {
            try {
                const payload = jwt.verify(token, secret, options)
                return payload
            } catch (e) {
                error = e
            }
        }
        if (options?.ignoreVerificationErrors) {
            return undefined
        }
        throw error
    }
}
