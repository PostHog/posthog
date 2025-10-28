import string
from collections import Counter, defaultdict
from datetime import datetime

import pandas as pd

responses_key = "We're adding more data sources!"

df = pd.read_csv("./posthog/temporal/data_imports/sources/export.csv")

# filter non strings
df = df[~df[responses_key].isna()]
df = df[~df[responses_key].isnull()]


# calc days ago for response
def days_ago(text: str):
    now = datetime.now()
    then = datetime.fromisoformat(text).replace(tzinfo=None)
    return (now - then).days


# all responses >= 90 days ago will get discounted the same
df["days_ago"] = df.apply(lambda row: min(days_ago(row["timestamp"]), 90), axis=1)

# calc discount
df["discount"] = 0.99 ** df["days_ago"]


# get words from responses
def keywords(text: str):
    return [word.strip(string.punctuation).lower() for word in text.split()]


df["keywords"] = df.apply(lambda row: keywords(row[responses_key]), axis=1)

# create word scores
words = Counter()
word_discounts = defaultdict(list)
for i, row in df.iterrows():
    words.update(row["keywords"])
    for word in row["keywords"]:
        word_discounts[word].append(row["discount"])

word_scores = [(word, sum(word_discounts[word]), words[word]) for word in words]
word_scores.sort(key=lambda x: (-x[1], -x[2], x[0]))

# create word pair scores
pairs = Counter()
pair_discounts = defaultdict(list)
blank_word = "<blank>"
for i, row in df.iterrows():
    if len(row["keywords"]) == 0:
        continue
    if len(row["keywords"]) < 2:
        word = row["keywords"][0]
        pairs.update([(word, blank_word)])
        pair_discounts[(word, blank_word)].append(row["discount"])
        continue
    row_pairs = []
    for i in range(1, len(row["keywords"])):
        pair = tuple(row["keywords"][i - 1 : i + 1])
        row_pairs.append(pair)
        pair_discounts[pair].append(row["discount"])
    pairs.update(row_pairs)

pair_scores = [(pair, sum(pair_discounts[pair]), pairs[pair]) for pair in pairs]
pair_scores.sort(key=lambda x: (-x[1], -x[2], x[0]))


def pretty_print_scores(scores):
    for i, el in enumerate(scores):
        text, score, count = el
        if not isinstance(text, str):
            text = " ".join(text).replace("null", "<blank>")
        print(f"{i + 1:02d}. {text:<40} {score:0.4f}, {count}")


print("SINGLE WORD SCORES\n")
pretty_print_scores(word_scores[:50])
print("\n" + "*" * 80 + "\n")
print("WORD PAIR SCORES\n")
pretty_print_scores(pair_scores[:50])
