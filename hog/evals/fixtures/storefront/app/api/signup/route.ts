export async function POST(request: Request) {
    const { email } = (await request.json()) as { email?: string }
    if (!email?.includes('@')) {
        return Response.json({ error: 'Enter a valid email.' }, { status: 400 })
    }
    return Response.json({ id: crypto.randomUUID(), email })
}
