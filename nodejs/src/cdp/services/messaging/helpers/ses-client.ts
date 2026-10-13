import { SESv2Client } from '@aws-sdk/client-sesv2'

export function createSesV2Client(config: { sesRegion: string; sesEndpoint: string }): SESv2Client | null {
    return config.sesRegion
        ? new SESv2Client({
              region: config.sesRegion,
              endpoint: config.sesEndpoint || undefined,
          })
        : null
}
