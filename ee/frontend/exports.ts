import { PostHogEE } from '@posthog/ee/types'

const myTestCode = (): void => {
    // eslint-disable-next-line no-console
    console.log('it works!')
}

const postHogEE: PostHogEE = {
    enabled: true,
    myTestCode,
}

export default postHogEE
