---
npm/hog: minor
---

hog now shows notices from PostHog after a command, such as a version reaching its end of support, with the update command for your install. They come in the release manifest and in PostHog API answers, so CI jobs with update checks off get them too. People see one line on stderr, agents get a JSON line, and GitHub Actions jobs also get an annotation on the run summary.
