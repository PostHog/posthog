/** Methods added by React before rendering the app */
import { FrontendAppConfig } from '~/types'

export interface FrontendAppSceneProps extends FrontendAppConfig {
    setConfig: (config: Record<string, any>) => Promise<void>
}

export interface FrontendAppSceneLogicProps {
    /** Used as the logic's key */
    id: number
}
