// @ts-nocheck

// ruleid: quill-text-destructive-needs-foreground
const Warning = <div className="text-xs text-destructive">Expires soon</div>

// ruleid: quill-text-destructive-needs-foreground
const Conditional = cn('font-semibold', hasErrors && 'text-destructive')

// ok: quill-text-destructive-needs-foreground
const Foreground = <div className="text-xs text-destructive-foreground">Expires soon</div>

// ok: quill-text-destructive-needs-foreground
const Lemon = <span className="text-success">Saved</span>

// ok: quill-text-destructive-needs-foreground
const Danger = <span className="text-danger">Failed</span>
