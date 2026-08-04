import { z } from 'zod'

export const PushNotificationPayloadSchema = z.object({
    // Common notification fields
    title: z.string(),
    body: z.string().optional(),
    image: z.string().url().optional(),
    data: z.record(z.string(), z.string()).optional(),
    collapseKey: z.string().optional(),
    ttlSeconds: z.number().int().min(0).optional(),
    // Android-specific overrides (used by FCM)
    android: z
        .object({
            priority: z.enum(['normal', 'high']).optional(),
            channelId: z.string().optional(),
            sound: z.string().optional(),
            tag: z.string().optional(),
            icon: z.string().optional(),
            color: z.string().optional(),
            clickAction: z.string().optional(),
        })
        .optional(),
    // iOS-specific overrides (used by FCM APNS bridge and direct APNS)
    apns: z
        .object({
            sound: z
                .union([
                    z.string(),
                    z.object({
                        name: z.string(),
                        critical: z.boolean().optional(),
                        volume: z.number().min(0).max(1).optional(),
                    }),
                ])
                .optional(),
            badge: z.number().int().optional(),
            category: z.string().optional(),
            threadId: z.string().optional(),
            interruptionLevel: z.enum(['passive', 'active', 'time-sensitive', 'critical']).optional(),
            relevanceScore: z.number().min(0).max(1).optional(),
            subtitle: z.string().optional(),
            contentAvailable: z.boolean().optional(),
            mutableContent: z.boolean().optional(),
            targetContentId: z.string().optional(),
        })
        .optional(),
})
