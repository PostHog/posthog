# PostHog Documentation in Monorepo

This directory contains developer-focused documentation that has been migrated from `posthog.com` into the `posthog` monorepo. This enables engineers to update docs alongside code in a single PR.

## Quick Start

- **For Published Docs** - See `./published/README.md`
- **For Internal Docs** - See `./internal/README.md`
- **Full Migration Plan** - See `./DOCS_MIGRATION_PLAN.md`
- **Build Guide** - See `./MONOREPO_DOCS_BUILD_GUIDE.md` (for posthog.com team)

## Directory Overview

```
docs/
├── published/              # Published on posthog.com 📖
│   ├── contributing/       # Contribution guides
│   ├── architecture/       # How PostHog works
│   ├── runbooks/           # Operational guides for self-hosters
│   ├── engineering/        # Engineering practices
│   └── README.md
├── internal/               # GitHub-only 🔒
│   ├── workflows/          # Development workflows
│   ├── migrations/         # Migration patterns
│   └── README.md
├── DOCS_MIGRATION_PLAN.md  # Strategy and scope
├── MONOREPO_DOCS_BUILD_GUIDE.md  # Setup for posthog.com
└── README.md              # This file
```

## What's Here

### Published Docs (20 files)
These are automatically built and published on posthog.com:

**Contributing** (4 files)
- Contributing guide for developers
- Code of conduct
- Badge system for contributors
- Recognition process

**Architecture** (6 files)
- System overview and data flow
- Data model explanation
- Event ingestion pipeline
- ClickHouse setup
- Query execution
- Session recording ingestion

**Runbooks** (2 files)
- Debugging plugin server jobs
- Managing scheduled tasks

**Total for Phase 1:** 12 files published

### Internal Docs (5 files)
GitHub-only documentation:

**Workflows**
- FLOX multi-instance development
- S3 query cache setup

**Other**
- Safe Django migrations guide
- Type baseline information

## Publishing Flow

```
Engineer commits to feature branch
    ↓
Push to GitHub
    ↓
PR created with /docs/** changes
    ↓
GitHub Action triggers preview build
    ↓
posthog.com builds from feature branch
    ↓
Preview URL posted to PR ✅
    ↓
Merge to master
    ↓
Production build includes new docs ✨
```

## For Monorepo Engineers

When updating these docs:
1. Edit files in `published/` or `internal/` as appropriate
2. Test locally if possible
3. Include doc updates in your feature PR
4. Reviewers can preview on posthog.com
5. Docs go live with code on merge

## For posthog.com Team

The build setup requires:
1. Configuring gatsby to read from `/docs/published/`
2. Adding GitHub Action to trigger preview builds
3. Filtering out `/docs/internal/` from builds

See `MONOREPO_DOCS_BUILD_GUIDE.md` for detailed setup instructions.

## Next Steps

This is Phase 1 of the docs migration. Testing PoC workflow with preview builds.

Planned for future phases:

- [ ] Verify build pipeline works with preview docs
- [ ] Move additional engineering handbook sections
- [ ] Move more operational runbooks
- [ ] Document cross-repo link strategy
- [ ] Set up redirects for deprecated posthog.com docs

## FAQ

**Q: Can I create docs in `/docs/internal/` even if not published?**
A: Yes! Internal docs stay in the repo with code and are searchable on GitHub. Perfect for internal-only content.

**Q: How do I test published docs locally?**
A: Set `POSTHOG_REPO_PATH` and run posthog.com locally. See MONOREPO_DOCS_BUILD_GUIDE.md.

**Q: What format should docs use?**
A: Same as posthog.com - Markdown/MDX with YAML frontmatter. Copy from existing docs for consistency.

**Q: When should I move a doc here vs keep it in posthog.com?**
A: Docs about PostHog internals and architecture → here. User product docs and tutorials → posthog.com.

**Q: How do I link between published docs?**
A: Use relative paths: `../contributing/index.md` or `./index.md`

## References

- [PostHog GitHub](https://github.com/PostHog/posthog)
- [PostHog Website](https://github.com/PostHog/posthog.com)
- [Contributing to PostHog](./published/contributing/index.md)
- [PostHog Architecture](./published/architecture/index.mdx)

