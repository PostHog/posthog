import { costs as fineTunedOpenAICosts } from "./openai/fine-tuned-models";
import { costs as togetherAIChatCosts } from "./togetherai/chat";
import { costs as togetherAIChatLlamaCosts } from "./togetherai/chat/llama";
import { costs as togetherAICompletionCosts } from "./togetherai/completion";
import { costs as togetherAICompletionLlamaCosts } from "./togetherai/completion";
import { costs as azureCosts } from "./azure";
import { costs as googleCosts } from "./google";
import { costs as cohereCosts } from "./cohere";
import { costs as mistralCosts } from "./mistral";
import { costs as openRouterCosts } from "./openrouter";
import { costs as fireworksAICosts } from "./fireworks";
import { costs as groqCosts } from "./groq";
import { ModelDetailsMap, ModelRow } from "../interfaces/Cost";
import { costs as qstashCosts } from "./qstash";
import { openAIProvider } from "./openai";
import { anthropicProvider } from "./anthropic";
import { costs as awsBedrockCosts } from "./awsBedrock";

const openAiPattern = /^https:\/\/api\.openai\.com/;
const anthropicPattern = /^https:\/\/api\.anthropic\.com/;
const azurePattern =
  /^(https?:\/\/)?([^.]*\.)?(openai\.azure\.com|azure-api\.net)(\/.*)?$/;
const localProxyPattern = /^http:\/\/127\.0\.0\.1:\d+\/v\d+\/?$/;
const heliconeProxyPattern = /^https:\/\/oai\.hconeai\.com/;
const amdbartekPattern = /^https:\/\/.*\.amdbartek\.dev/;
const anyscalePattern = /^https:\/\/api\.endpoints\.anyscale\.com/;
const cloudflareAiGatewayPattern = /^https:\/\/gateway\.ai\.cloudflare\.com/;
const twoYFV = /^https:\/\/api\.2yfv\.com/;
const togetherPattern = /^https:\/\/api\.together\.xyz/;
const lemonFox = /^https:\/\/api\.lemonfox\.ai/;
const fireworks = /^https:\/\/api\.fireworks\.ai/;
const perplexity = /^https:\/\/api\.perplexity\.ai/;
const googleapis = /^https:\/\/(.*\.)?googleapis\.com/;
// openrouter.ai or api.openrouter.ai
const openRouter = /^https:\/\/(api\.)?openrouter\.ai/;
//api.wisdominanutshell.academy
const wisdomInANutshell = /^https:\/\/api\.wisdominanutshell\.academy/;
// api.groq.com
const groq = /^https:\/\/api\.groq\.com/;
// cohere.ai
const cohere = /^https:\/\/api\.cohere\.ai/;
// api.mistral.ai
const mistral = /^https:\/\/api\.mistral\.ai/;
// https://api.deepinfra.com
const deepinfra = /^https:\/\/api\.deepinfra\.com/;
//https://qstash.upstash.io/llm
const qstash = /^https:\/\/qstash\.upstash\.io/;
//https://www.firecrawl.dev/
const firecrawl = /^https:\/\/api\.firecrawl\.dev/;
// https://bedrock-runtime.{some-region}.amazonaws.com/{something-after}
const awsBedrock = /^https:\/\/bedrock-runtime\.[a-z0-9-]+\.amazonaws\.com\/.*/;

export const providersNames = [
  "OPENAI",
  "ANTHROPIC",
  "AZURE",
  "LOCAL",
  "HELICONE",
  "AMDBARTEK",
  "ANYSCALE",
  "CLOUDFLARE",
  "2YFV",
  "TOGETHER",
  "LEMONFOX",
  "FIREWORKS",
  "PERPLEXITY",
  "GOOGLE",
  "OPENROUTER",
  "WISDOMINANUTSHELL",
  "GROQ",
  "COHERE",
  "MISTRAL",
  "DEEPINFRA",
  "QSTASH",
  "FIRECRAWL",
  "AWS",
] as const;

export type ProviderName = (typeof providersNames)[number];

export type ModelNames = (typeof modelNames)[number];

export const providers: {
  pattern: RegExp;
  provider: ProviderName;
  costs?: ModelRow[];
  modelDetails?: ModelDetailsMap;
}[] = [
  {
    pattern: openAiPattern,
    provider: "OPENAI",
    costs: [...openAIProvider.costs, ...fineTunedOpenAICosts],
    modelDetails: openAIProvider.modelDetails,
  },
  {
    pattern: anthropicPattern,
    provider: "ANTHROPIC",
    costs: anthropicProvider.costs,
    modelDetails: anthropicProvider.modelDetails,
  },
  {
    pattern: azurePattern,
    provider: "AZURE",
    costs: [...azureCosts, ...openAIProvider.costs],
  },
  {
    pattern: localProxyPattern,
    provider: "LOCAL",
  },
  {
    pattern: heliconeProxyPattern,
    provider: "HELICONE",
  },
  {
    pattern: amdbartekPattern,
    provider: "AMDBARTEK",
  },
  {
    pattern: anyscalePattern,
    provider: "ANYSCALE",
  },
  {
    pattern: cloudflareAiGatewayPattern,
    provider: "CLOUDFLARE",
  },
  {
    pattern: twoYFV,
    provider: "2YFV",
  },
  {
    pattern: togetherPattern,
    provider: "TOGETHER",
    costs: [
      ...togetherAIChatCosts,
      ...togetherAIChatLlamaCosts,
      ...togetherAICompletionCosts,
      ...togetherAICompletionLlamaCosts,
    ],
  },
  {
    pattern: lemonFox,
    provider: "LEMONFOX",
  },
  {
    pattern: fireworks,
    provider: "FIREWORKS",
    costs: fireworksAICosts,
  },
  {
    pattern: perplexity,
    provider: "PERPLEXITY",
  },
  {
    pattern: googleapis,
    provider: "GOOGLE",
    costs: googleCosts,
  },
  {
    pattern: openRouter,
    provider: "OPENROUTER",
    costs: openRouterCosts,
  },
  {
    pattern: wisdomInANutshell,
    provider: "WISDOMINANUTSHELL",
  },
  {
    pattern: groq,
    provider: "GROQ",
    costs: groqCosts,
  },
  {
    pattern: cohere,
    provider: "COHERE",
    costs: cohereCosts,
  },
  {
    pattern: mistral,
    provider: "MISTRAL",
    costs: mistralCosts,
  },
  {
    pattern: deepinfra,
    provider: "DEEPINFRA",
  },
  {
    pattern: qstash,
    provider: "QSTASH",
    costs: qstashCosts,
  },
  {
    pattern: firecrawl,
    provider: "FIRECRAWL",
  },
  {
    pattern: awsBedrock,
    provider: "AWS",
    costs: awsBedrockCosts,
  },
];

export const playgroundModels: {
  name: string;
  provider: ProviderName;
}[] =
  (providers
    .map((provider) => {
      return provider.costs
        ?.filter((cost) => cost.showInPlayground)
        .map((cost) => ({
          name: cost.model.value,
          provider: provider.provider,
        }));
    })
    .flat()
    .filter((model) => model !== undefined) as {
    name: string;
    provider: ProviderName;
  }[]) ?? [];

// eslint-disable-next-line @typescript-eslint/no-non-null-assertion
export const defaultProvider = providers.find(
  (provider) => provider.provider === "OPENAI"
)!;

export const allCosts = providers.flatMap((provider) => provider.costs ?? []);

export const approvedDomains = providers.map((provider) => provider.pattern);

export const modelNames = allCosts.map((cost) => cost.model.value);

export const parentModelNames = providers.reduce((acc, provider) => {
  if (provider.modelDetails) {
    acc[provider.provider] = Object.keys(provider.modelDetails);
  }
  return acc;
}, {} as Record<ProviderName, string[]>);
