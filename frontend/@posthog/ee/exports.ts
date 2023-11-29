import { PostHogEE } from './types'

export default async (): Promise<PostHogEE> => {
    // this is slightly ridiculous, as far as I can tell esbuild doesn't support dynamic imports
    // unless you pass string concatenations to it, so we have to do this
    // the `wat` variable - because it is preceded by a slash
    // is expanded to \**\*
    // so we try to import a file *exports.ts from the ee\frontend folder
    // instead of simply importing the file using a static string
    // I basically can't believe this
    const wat = 'exports'
    try {
        return (await import(`../../../ee/frontend/${wat}exports.ts`)).default()
    } catch (e) {
        return {
            enabled: false,
        }
    }
}
