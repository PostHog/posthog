/** Config passed to app from Django's app context */
export interface FrontendAppConfig {
    id: number
    name: string
    url: string
    config: Record<string, any>
}

/** Methods added by React before rendering the app */
export interface FrontendAppSceneProps extends FrontendAppConfig {
    setConfig: (config: Record<string, any>) => Promise<void>
}

export interface FrontendAppSceneLogicProps {
    /** Used as the logic's key */
    id: number
}
