import { Express } from 'ultimate-express'

export function registerHealth(app: Express): void {
    app.get('/health', (_req, res) => {
        res.json({ ok: true })
    })
}
