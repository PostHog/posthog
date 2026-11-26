# AI assistants / answer engines. GA4 and Matomo both ship a default "AI" channel group; like Matomo
# (but unlike GA4, which keeps it under Search) we include Perplexity here. Entries cover both bare
# utm_source values and referrer domains. No paid type: AI clicks with paid click IDs or mediums fall
# through to the generic paid rules.
AI_SOURCES: tuple[str, ...] = (
    # OpenAI
    "chatgpt",
    "chatgpt.com",
    "chat.openai.com",
    # Anthropic
    "claude",
    "claude.ai",
    # Google
    "gemini",
    "gemini.google.com",
    # Microsoft
    "copilot",
    "copilot.microsoft.com",
    "copilot.cloud.microsoft",
    # xAI
    "grok",
    "grok.com",
    # DeepSeek
    "deepseek",
    "deepseek.com",
    "chat.deepseek.com",
    # Meta
    "meta.ai",
    # Mistral
    "chat.mistral.ai",
    # Perplexity
    "perplexity.ai",
    "ai.perplexity.app",
    # other answer engines / AI assistants
    "phind.com",
    "andisearch.com",
    "komo.ai",
    "you.com",
    "poe.com",
    "hey.pi.ai",
    "genspark.ai",
    "chat.genspark.ai",
    "felo.ai",
    "chat.felo.ai",
    "t3.chat",
    "iask.ai",
    "venice.ai",
    "lumo.proton.me",
    "duck.ai",
    "manus.im",
    # Chinese / regional AI assistants
    "chat.qwen.ai",
    "doubao.com",
    "kimi.com",
    "yiyan.baidu.com",
    "ernie.baidu.com",
    "chatglm.cn",
    "yuanbao.tencent.com",
    "hunyuan.tencent.com",
    "xinghuo.xfyun.cn",
    "giga.chat",
    "sarvam.ai",
)
